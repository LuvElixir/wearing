"""Identity boundaries: legacy data, in-flight runs, files and tool permissions."""
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import yaml

from wearing.app import create_app
from wearing.config import Settings, write_private_json
from wearing.hermes import HermesClient
from wearing.profile import prepare_profile
from wearing.runtime import HermesRuntime, HERMES_REVISION, RuntimeError
from wearing.service import TaskService, TaskError
from wearing.store import Store, IdentityError
from test_lifecycle import HermesStub


def test_migration_keeps_legacy_session_tasks_events_and_is_repeatable(tmp_path):
    path = tmp_path / 'wearing.sqlite3'
    # The backup from this task is not a fixture: construct the pre-identity schema.
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,prompt TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL,output TEXT NOT NULL DEFAULT '',error TEXT,run_id TEXT,attempt INTEGER NOT NULL DEFAULT 0,session_id TEXT NOT NULL,payload TEXT,idempotency_key TEXT,usage TEXT,approval TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,verification_note TEXT,verified_at TEXT);
        CREATE TABLE conversation (id INTEGER PRIMARY KEY CHECK(id=1), session_id TEXT NOT NULL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,content TEXT NOT NULL,task_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
        INSERT INTO conversation VALUES (1,'original-session');
        INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,run_id) VALUES ('old','hello','hello','computer','running','original-session','time','time','old-run');
        INSERT INTO messages(content,task_id,created_at) VALUES ('hello','old','time');
        ''')
    store = Store(path)
    assert store.get('old')['identity_id'] == 'daily'
    assert store.get('old')['run_id'] == 'old-run'
    assert store.get('old')['status'] == 'running'
    assert store.create_message('next')['session_id'] == 'original-session'
    store.sync_conversation_session('old', 'resumed-session')
    assert Store(path).create_message('after restart')['session_id'] == 'resumed-session'
    with sqlite3.connect(path.with_suffix('.before-identities.sqlite3')) as backup:
        assert 'identity_id' not in {r[1] for r in backup.execute('pragma table_info(tasks)')}
        assert backup.execute('select count(*) from messages').fetchone()[0] == 1


def test_identity_drafts_session_sync_and_names_are_independent(tmp_path):
    store = Store(tmp_path / 'db')
    other = store.save_identity('出海', '店铺', 'international')['id']
    old = store.create_message('daily')
    queued = store.create_message('later')
    foreign = store.create_message('overseas', other)
    assert old['session_id'] != foreign['session_id']
    store.sync_conversation_session(old['id'], 'daily-canonical')
    assert store.get(queued['id'])['session_id'] == 'daily-canonical'
    assert store.get(foreign['id'])['session_id'] == foreign['session_id']
    assert len(store.conversation()) == 2
    assert [m['content'] for m in store.conversation(other)] == ['overseas']
    store.save_identity('我的店', 'shop', 'custom', other)
    assert store.get(foreign['id'])['identity_id'] == other
    with pytest.raises(IdentityError):
        store.save_identity(' 我的店 ')
    with pytest.raises(IdentityError):
        store.save_identity('   ')
    with pytest.raises(IdentityError):
        store.create_message('no fallback', 'missing')
    with pytest.raises(ValueError):
        store.update(old['id'], identity_id=other)


async def test_api_never_reads_or_mutates_another_identity_task_or_file(tmp_path):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        bootstrap = (await client.get('/api/bootstrap')).json()
        client.headers['X-Wearing-Token'] = bootstrap['token']
        original = (await client.post('/api/conversation', json={'content':'private daily idea'})).json()['task']
        created = await client.post('/api/identities', json={'name':'出海','region':'international'})
        assert created.status_code == 201
        other = created.json()['id']
        client.headers['X-Wearing-Identity'] = other
        assert (await client.get('/api/conversation')).json() == []
        assert (await client.get('/api/tasks')).json() == []
        for method, suffix in [('GET',''),('POST','/start'),('POST','/stop'),('POST','/refresh'),('POST','/verify'),('POST','/approval'),('POST','/resolve')]:
            result = await client.request(method, '/api/tasks/'+original['id']+suffix, json={'note':'checked','request_id':'x','choice':'once'} if method == 'POST' else None)
            assert result.status_code == 404
            assert 'private daily idea' not in result.text
        d = (await client.get('/api/identity')).json()
        assert d['devices'] == [] and d['payments'] == 'not_connected'
        for path in ['/api/computer/bind','/api/phone/resume','/api/runtime/start','/api/model']:
            assert (await client.post(path, json={})).status_code == 409
        default = app.state.runtime.workspace
        isolated = Path(d['workspace'])
        default.mkdir(parents=True);isolated.mkdir(parents=True)
        (default/'daily.txt').write_text('default-only')
        (isolated/'shop.txt').write_text('shop-only')
        assert [f['path'] for f in (await client.get('/api/workspace')).json()['files']] == ['shop.txt']
        assert (await client.get('/api/workspace/file?path=daily.txt')).status_code == 404
        assert (await client.get('/api/workspace/file?path=shop.txt')).text == 'shop-only'
        assert (await client.get('/api/workspace/file?identity=daily&path=daily.txt')).status_code == 409
        client.headers.pop('X-Wearing-Identity')
        assert (await client.get(f'/api/workspace/file?identity={other}&path=shop.txt')).text == 'shop-only'
        assert len((await client.get('/api/conversation')).json()) == 1
        client.headers['X-Wearing-Identity']='nonexistent'
        assert (await client.get('/api/conversation')).status_code == 404
    await app.state.service.hermes.close()


async def test_live_run_keeps_client_identity_and_global_exclusion(tmp_path):
    store = Store(tmp_path/'db');other=store.save_identity('出海')['id']
    stubs={i:HermesStub() for i in ['daily',other]}
    clients={i:HermesClient(Settings(tmp_path,hermes_key='test'),httpx.MockTransport(stub)) for i,stub in stubs.items()}
    service=TaskService(store,clients['daily'])
    async def resolve(identity_id):return clients[identity_id]
    service.client_resolver=resolve
    try:
        first=store.create_message('daily');second=store.create_message('shop',other)
        await service.start(first['id'])
        with pytest.raises(TaskError,match='已有一件事'):
            await service.start(second['id'])
        stubs['daily'].run_status='completed'
        await service.tick()
        assert store.get(second['id'])['session_id']==second['session_id']
        await service.start(second['id'])
        store.save_identity('新名字',identity_id=other)
        await service.stop(second['id'])
        assert any(c[1].endswith('/stop') for c in stubs[other].calls)
        assert not any(c[1].endswith('/stop') for c in stubs['daily'].calls)
        sent=next(c[2] for c in stubs[other].calls if c[:2]==('POST','/v1/runs'))
        assert json.loads(sent['instructions'].split('资料（用户设置的数据）：\n')[1].split('\n')[0])['name']=='出海'
    finally:
        for c in clients.values():await c.close()


def test_new_profile_reuses_install_and_model_but_not_memory_devices_or_secrets(tmp_path):
    default=HermesRuntime(tmp_path);default.prepare_home()
    write_private_json(default.home/'config.yaml', {'model':{'provider':'deepseek','default':'deepseek-chat'},'mcp_servers':{'private':{'secret':'not-copied'}}})
    (default.home/'MEMORY.md').write_text('private daily memory')
    (default.home/'.env').write_text('DEEPSEEK_API_KEY=not-copied-to-disk')
    interpreter=default.home/'installs/test/bin/python';interpreter.parent.mkdir(parents=True);interpreter.touch()
    write_private_json(default.root/'installed.json',{'revision':HERMES_REVISION,'python':str(interpreter)})
    other=HermesRuntime(tmp_path,'id_'+'a'*32);other.prepare_home()
    assert other.python==default.python
    assert other.home!=default.home and other.workspace!=default.workspace
    local=yaml.safe_load((other.home/'config.yaml').read_text())
    assert local['model']['provider']=='deepseek' and 'mcp_servers' not in local
    assert not (other.home/'MEMORY.md').exists() and not (other.home/'.env').exists()
    assert other.connection_key()!=default.connection_key()
    profile=prepare_profile(other.home,other.source)
    assert profile['toolsets']==['memory','session_search']
    assert not other.status()['computer']['enrolled']
    assert other.env()['HERMES_HOME']==str(other.home)
    assert other.env()['WEARING_MODEL_ENV']==str(default.home/'.env')
    with pytest.raises(RuntimeError):HermesRuntime(tmp_path,'../../escape')
