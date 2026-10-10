"""Actual private-instance ledger, HTTP boundary and SDK dispatch without network."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import httpx
import pytest

from wearing.ai_consent import ConsentBook, ConsentError, POLICY_VERSION
from wearing.cloud.instance import initialize_instance
from wearing.cloud.worker import create_tenant_app

ACTOR = 'a' * 64


@pytest.fixture
def book(tmp_path):
    root = tmp_path / 'instance'
    initialize_instance(root, 'tenant_fixture', 'https://consent.example')
    return ConsentBook(root / 'data', create=True)


def decide(book, action='accept', revision=0, actor=ACTOR, identity='daily', request=None):
    return book.change(identity, actor, action=action, policy_version=POLICY_VERSION,
                       expected_revision=revision, request_id=request or uuid.uuid4().hex)


def test_default_deny_restart_revoke_historical_receipt_and_provider(book):
    assert book.snapshot('daily', ACTOR)['state'] == 'not_granted'
    with pytest.raises(ConsentError): book.require('daily')
    key = uuid.uuid4().hex
    accepted = decide(book, request=key)
    assert accepted['accepted'] and accepted['revision'] == 1
    restarted = ConsentBook(book.data_dir)
    restarted.require('daily', actor=ACTOR)
    for identity, origin in [('another', 'https://api.deepseek.com'), ('daily', 'https://other.example'), ('daily', 'http://api.deepseek.com')]:
        with pytest.raises(ConsentError): restarted.require(identity, origin=origin)
    decide(restarted, 'revoke', 1)
    with pytest.raises(ConsentError): book.require('daily')
    replay = decide(book, request=key)
    assert replay['state'] == 'revoked' and not replay['accepted']
    assert replay['receipt']['revision'] == 1 and replay['revision'] == 2
    with pytest.raises(ConsentError, match='暂时无法核对'):
        decide(book, 'revoke', 0, request=key)


def test_anchor_atomic_and_never_inherits_another_owner_or_instance(book, tmp_path):
    def attempt(actor):
        try: return decide(book, actor=actor)
        except ConsentError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [ACTOR, 'b' * 64]))
    assert sum(isinstance(x, dict) for x in results) == 1
    assert 'ai_consent_owner_changed' in results
    winner = ACTOR if isinstance(results[0], dict) else 'b' * 64
    other = 'b' * 64 if winner == ACTOR else ACTOR
    with pytest.raises(ConsentError): book.snapshot('daily', other)
    root = tmp_path / 'foreign'
    initialize_instance(root, 'tenant_foreign', 'https://consent.example')
    shutil.copyfile(book.path, root / 'data/ai-consent.sqlite3')
    (root / 'data/ai-consent.sqlite3').chmod(0o600)
    with pytest.raises(ConsentError): ConsentBook(root / 'data').require('daily')


def test_cas_policy_change_and_unsafe_or_deleted_ledger_fail_closed(book, monkeypatch):
    decide(book)
    with pytest.raises(ConsentError): decide(book, 'revoke', 0)
    monkeypatch.setattr('wearing.ai_consent.POLICY_VERSION', 'deepseek-new-policy')
    assert not book.snapshot('daily', ACTOR)['accepted']
    with pytest.raises(ConsentError): book.require('daily')
    book.path.chmod(0o644)
    with pytest.raises(ConsentError): book.require('daily')
    book.path.chmod(0o600); book.path.unlink()
    with pytest.raises(ConsentError): book.require('daily')


@pytest.mark.asyncio
async def test_actual_tenant_api_csrf_owner_and_strict_body(tmp_path, monkeypatch):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root = tmp_path / 'instance'
    initialize_instance(root, 'tenant_fixture', 'https://consent.example')
    app = create_tenant_app(root, engine_autostart=False)
    auth = {'Authorization': 'Bearer ' + (root / 'gateway.key').read_text().strip(), 'X-Wearing-Tenant': 'tenant_fixture',
            'X-Pajio-Storage-Scope': ACTOR, 'X-Pajio-Private-Owner-Scope': ACTOR}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://consent.example', headers=auth) as client:
        before = await client.get('/api/ai-consent')
        assert before.status_code == 200 and before.json()['revision'] == 0
        assert 'no-store' in before.headers['cache-control']
        payload = dict(action='accept', policy_version=POLICY_VERSION, expected_revision=0, request_id=uuid.uuid4().hex)
        assert (await client.post('/api/ai-consent', json=payload)).status_code == 403
        token = (await client.get('/api/bootstrap')).json()['token']
        client.headers['X-Wearing-Token'] = token
        assert (await client.post('/api/ai-consent', json={**payload, 'owner': ACTOR})).status_code == 422
        accepted = await client.post('/api/ai-consent', json=payload)
        assert accepted.status_code == 200 and accepted.json()['accepted']
        assert ACTOR not in accepted.text and 'tenant_fixture' not in accepted.text
        assert (await client.post('/api/ai-consent', json=payload)).json()['receipt']['revision'] == 1
        client.headers['X-Pajio-Private-Owner-Scope'] = 'b' * 64
        assert (await client.get('/api/ai-consent')).status_code == 403
        client.headers['X-Pajio-Storage-Scope'] = 'b' * 64
        denied = await client.get('/api/ai-consent')
        assert denied.status_code == 403 and denied.json()['code'] == 'ai_consent_owner_changed'
        del client.headers['X-Pajio-Private-Owner-Scope']
        assert (await client.get('/api/ai-consent')).status_code == 403
        del client.headers['Authorization']
        assert (await client.get('/api/ai-consent')).status_code == 401


@pytest.mark.asyncio
async def test_cloud_capture_requires_own_decision_but_manual_save_still_works(tmp_path, monkeypatch):
    from wearing.capture import CaptureDraft
    from wearing.life import LifeDraft
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root = tmp_path / 'instance'
    initialize_instance(root, 'tenant_fixture', 'https://consent.example')
    app = create_tenant_app(root, engine_autostart=False)
    captures, worker = app.state.captures, app.state.capture_worker
    consent = ConsentBook(root/'data', create=True)
    old = captures.create('daily', CaptureDraft(record=LifeDraft(kind='note', title='old fixture'), request_key='old-fixture'))
    calls = []
    async def command(*args, **kwargs): calls.append(True); raise AssertionError('No native/model command permitted')
    monkeypatch.setattr(worker, 'command', command)
    decide(consent)
    await worker.run(captures.claim())
    assert captures.get('daily', old['id'])['state'] == 'failed' and not calls
    owned = captures.create('daily', CaptureDraft(record=LifeDraft(kind='note', title='owned fixture'), request_key='own-fixture'), owner_scope=ACTOR)
    decide(consent, 'revoke', 1)
    await worker.run(captures.claim())
    assert captures.get('daily', owned['id'])['state'] == 'failed' and not calls
    plain = captures.create('daily', CaptureDraft(record=LifeDraft(kind='note', title='manual fixture'), request_key='manual-fixture', organize=False))
    assert captures.get('daily', plain['id'])['state'] == 'saved'


@pytest.mark.asyncio
async def test_real_core_task_paths_deny_without_consent_and_after_revoke(book, monkeypatch):
    from wearing.app import create_app
    from wearing.briefing_api import CreateBriefing
    from wearing.config import Settings
    from wearing.hermes import HermesClient
    from wearing.schedules import ScheduleDraft
    from wearing.service import TaskError

    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '0')  # Consent cannot depend on pricing being enabled.
    calls, guarded = [], [False]

    def wire(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/v1/capabilities':
            return httpx.Response(200, json={'features': {}, 'wearing': {'ai_consent_guard': 'deepseek-v1' if guarded[0] else None}})
        assert request.method == 'POST' and request.url.path == '/v1/runs'
        return httpx.Response(200, json={'run_id': 'synthetic-run'})

    settings = Settings(book.data_dir, hermes_key='synthetic')
    client = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, hermes=client, local_devices=False)
    service, store = app.state.service, app.state.store
    try:
        chat = await service.submit_message('Synthetic consent test', 'daily', uuid.uuid4().hex, owner_scope=ACTOR)
        assert chat['delivery'] == 'saved' and chat['task']['status'] == 'draft' and not calls
        brief = await app.state.briefings.create('daily', CreateBriefing(date='2026-10-10', request_key=uuid.uuid4().hex), service, owner_scope=ACTOR)
        assert brief['state'] == 'not_started' and not brief['artifacts'] and not calls

        decide(book)
        task = store.create('Synthetic direct task', 'computer', owner_scope=ACTOR)
        with pytest.raises(TaskError, match='引擎尚未启用'):
            await service.start(task['id'])  # A stale engine is not trusted to enforce revocation.
        assert calls == [('GET', '/v1/capabilities')]
        guarded[0] = True
        assert (await service.start(task['id']))['status'] == 'running'
        assert sum(method == 'POST' for method, _ in calls) == 1
        store.update(task['id'], status='completed_unverified')
        before = list(calls)

        # Background sources retain the trusted originating actor across their later claim.
        goal = app.state.goals.create('daily', 'Synthetic goal', 'No real data', 'A fixture response', owner_scope=ACTOR)
        app.state.goals.control(goal['id'], goal['revision'], 'resume', owner_scope=ACTOR)
        goal_task = app.state.goals.claim(goal['id'])
        clock = ['2026-10-10T00:00:00+00:00']
        monkeypatch.setattr('wearing.schedules.now', lambda: clock[0])
        scheduled = app.state.schedules.create('daily', ScheduleDraft(title='Fixture', instruction='Synthetic only', kind='once', at='2026-10-10T00:01:00+00:00'), uuid.uuid4().hex, owner_scope=ACTOR)
        clock[0] = '2026-10-10T00:01:01+00:00'
        schedule_task = app.state.schedules.claim(scheduled['id'])
        assert goal_task and schedule_task
        decide(book, 'revoke', 1)
        for pending in (goal_task, schedule_task):
            with pytest.raises(TaskError, match='明确同意'):
                await service.start(pending['id'])
            assert store.get(pending['id'])['status'] == 'draft'
        assert calls == before

        decide(book, 'accept', 2)
        for actor in (None, 'b' * 64):
            foreign = store.create('Unowned/foreign fixture', 'computer', owner_scope=actor)
            with pytest.raises(TaskError): await service.start(foreign['id'])
        assert calls == before
    finally:
        await client.close()


@pytest.mark.parametrize('trial', [True, False])
def test_installed_sdk_sync_async_child_aux_and_revocation_without_trial_switch(tmp_path, trial):
    installed = Path(__file__).parents[1] / '.wearing/runtime/installed.json'
    if not installed.exists(): pytest.skip('Managed Hermes SDK unavailable')
    python = Path(json.loads(installed.read_text())['python'])
    if not python.is_file(): pytest.skip('Managed Hermes SDK unavailable')
    initialize_instance(tmp_path / 'instance', 'fixture', 'https://consent.example')
    script = r'''
import asyncio,json,sys,types,uuid
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import httpx
from openai import OpenAI,AsyncOpenAI
from wearing.ai_consent import ConsentBook,ConsentError,POLICY_VERSION
from wearing.usage_guard import UsageGuardConfig,install_usage_guard
from wearing.usage import UsageError,UsageBook
root=Path(sys.argv[2])/'instance'
b=ConsentBook(root/'data',create=True);actor='a'*64
calls=[]
def response(req):
 calls.append(req)
 if req.method=='GET':return httpx.Response(200,json={'object':'list','data':[]})
 return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}]})
client=OpenAI(api_key='synthetic',base_url='https://api.deepseek.com:443/v1',http_client=httpx.Client(transport=httpx.MockTransport(response)))
aux=types.ModuleType('agent.auxiliary_client')
aux._resolve_call_client=lambda client:types.SimpleNamespace(client=client)
for n in ('_relay_sync_completion','_relay_sync_stream','_relay_async_completion'):setattr(aux,n,lambda client:client.chat.completions.create(model='fixture',messages=[]))
agent=types.ModuleType('agent');agent.auxiliary_client=aux;sys.modules['agent']=agent
class Agent:
 def __init__(self,provider='deepseek',api_mode='chat_completions',fallback_model=None):self.provider=provider;self.api_mode=api_mode
run=types.ModuleType('run_agent');run.AIAgent=Agent;sys.modules['run_agent']=run
trial=sys.argv[3]=='1'
assert install_usage_guard(UsageGuardConfig(trial,root/'data','daily',True))
for send in (lambda:client.chat.completions.create(model='fixture',messages=[]),lambda:aux._relay_sync_completion(client)):
 try:send()
 except ConsentError:pass
 else:raise AssertionError('Unconsented data reached network')
assert calls==[]
assert client.models.list().data==[]
assert len(calls)==1 and calls[0].method=='GET'
calls.clear()
for path,options in (('/chat/completions',{}),('/models',{'params':{'prompt':'synthetic'}})):
 try:client.get(path,cast_to=dict,options=options)
 except ConsentError:pass
 else:raise AssertionError('GET sent unconsented data')
assert calls==[]
if trial:assert UsageBook(root/'data',enabled=True).snapshot('daily')['identity_usage']['calls']==0
b.change('daily',actor,action='accept',policy_version=POLICY_VERSION,expected_revision=0,request_id=uuid.uuid4().hex)
assert client.chat.completions.create(model='fixture',messages=[]).choices[0].message.content=='ok'
assert aux._relay_sync_completion(client).choices[0].message.content=='ok'
child=Agent();assert child._fallback_chain==[] and child._fallback_model is None
try:Agent(provider='bedrock')
except UsageError:pass
else:raise AssertionError('Non-SDK child bypass')
try:aux._resolve_call_client(object())
except UsageError:pass
else:raise AssertionError('Non-SDK aux bypass')
foreign=OpenAI(api_key='synthetic',base_url='https://other.example/v1',http_client=httpx.Client(transport=httpx.MockTransport(response)))
try:foreign.chat.completions.create(model='fixture',messages=[])
except ConsentError as e:assert e.code=='ai_provider_not_supported'
else:raise AssertionError('Provider change reused consent')
b.change('daily',actor,action='revoke',policy_version=POLICY_VERSION,expected_revision=1,request_id=uuid.uuid4().hex)
async def check():
 c=AsyncOpenAI(api_key='synthetic',base_url='https://api.deepseek.com',http_client=httpx.AsyncClient(transport=httpx.MockTransport(response)))
 try:await c.chat.completions.create(model='fixture',messages=[])
 except ConsentError:pass
 else:raise AssertionError('Async bypassed revocation')
 await c.close()
asyncio.run(check())
try:client.chat.completions.create(model='fixture',messages=[])
except ConsentError:pass
else:raise AssertionError('Sync bypassed revocation')
assert len(calls)==2
if trial:assert UsageBook(root/'data',enabled=True).snapshot('daily')['identity_usage']['calls']==2
else:assert not (root/'data/usage.sqlite3').exists()
# Exercise a real reservation committing concurrently with a revoke before send.
if trial:
 b.change('daily',actor,action='accept',policy_version=POLICY_VERSION,expected_revision=2,request_id=uuid.uuid4().hex)
 original_reserve=UsageBook.reserve
 def reserve_then_revoke(self,*args,**kwargs):
  result=original_reserve(self,*args,**kwargs)
  b.change('daily',actor,action='revoke',policy_version=POLICY_VERSION,expected_revision=3,request_id=uuid.uuid4().hex)
  return result
 UsageBook.reserve=reserve_then_revoke
 try:client.chat.completions.create(model='fixture',messages=[])
 except ConsentError:pass
 else:raise AssertionError('Budget wait bypassed completed withdrawal')
 assert len(calls)==2
 view=UsageBook(root/'data',enabled=True).snapshot('daily')
 assert view['resources']['model']['active']==0
 with UsageBook(root/'data',enabled=True)._db() as db:
  row=db.execute('SELECT input_tokens,output_tokens,state FROM trial_calls ORDER BY created_at DESC LIMIT 1').fetchone()
  assert tuple(row)==(0,0,'completed')
print('consent-sdk-pass')
'''
    result = subprocess.run([str(python), '-c', script, str(Path(__file__).parents[1]/'src'), str(tmp_path), '1' if trial else '0'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-5000:]
    assert 'consent-sdk-pass' in result.stdout
