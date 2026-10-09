"""Exercise actual installed SDK through a MockTransport, never paid network."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import pytest


def test_installed_openai_sdk_nonstream_stream_error_and_quota_boundaries(tmp_path):
    installed = Path(__file__).parents[1] / '.wearing/runtime/installed.json'
    if not installed.exists(): pytest.skip('Managed Hermes SDK is not installed')
    python = Path(json.loads(installed.read_text())['python'])
    if not python.is_file(): pytest.skip('Managed Hermes SDK interpreter unavailable')
    script = r'''
import sys, json, asyncio, os, types
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import httpx
from openai import OpenAI, AsyncOpenAI
from wearing.usage import UsageBook, UsagePolicy, UsageError
from wearing.usage_guard import UsageGuardConfig, install_usage_guard
b=UsageBook(Path(sys.argv[2]), UsagePolicy(model_calls=6, model_concurrency=1), enabled=True)
os.environ.update(PAJIO_TRIAL_LIMITS='1', PAJIO_USAGE_DATA_DIR=sys.argv[2], PAJIO_USAGE_IDENTITY='daily')
config=UsageGuardConfig.from_env()
reroute=Path(sys.argv[2])/'another-tenant'
provider_env=Path(sys.argv[2])/'.env'
provider_env.write_text('PAJIO_TRIAL_LIMITS=0\nPAJIO_USAGE_DATA_DIR="'+str(reroute)+'"\nPAJIO_USAGE_IDENTITY=other\n')
from dotenv import load_dotenv
load_dotenv(provider_env,override=True)
assert os.environ['PAJIO_TRIAL_LIMITS']=='0'
# Only upstream agent construction is stubbed; the SDK, dotenv, transport,
# installer and durable reservation/settlement path are real.
aux=types.ModuleType('agent.auxiliary_client')
for name in ('_resolve_call_client','_relay_sync_completion','_relay_sync_stream','_relay_async_completion'):
 setattr(aux,name,lambda *args,**kwargs: None)
agent_module=types.ModuleType('agent');agent_module.auxiliary_client=aux
sys.modules['agent']=agent_module
class Agent:
 def __init__(self,provider='deepseek',api_mode='chat_completions',fallback_model='unsafe'):
  self.provider=provider;self.api_mode=api_mode
  self._fallback_chain=['unsafe'];self._fallback_model=fallback_model;self._fallback_index=4
run_agent=types.ModuleType('run_agent');run_agent.AIAgent=Agent;sys.modules['run_agent']=run_agent
assert install_usage_guard(config)
assert install_usage_guard(config)
a=Agent()
assert a._fallback_chain==[] and a._fallback_model is None and a._fallback_index==0
try: Agent(provider='bedrock')
except UsageError as error: assert error.code=='quota_provider'
else: raise AssertionError('dotenv disabled the agent provider guard')
for changed in (UsageGuardConfig(False), UsageGuardConfig(True,reroute,'other')):
 try: install_usage_guard(changed)
 except UsageError as error: assert error.code=='quota_unavailable'
 else: raise AssertionError('An installed guard changed authority')
seen=[]
def respond(request):
 if request.method=='GET': return httpx.Response(200,json={'object':'list','data':[]})
 body=json.loads(request.content); seen.append(body)
 if body['model']=='failed': return httpx.Response(503,json={'error':{'message':'provider unavailable'}})
 if body.get('stream'):
  chunks=[{'id':'stream','object':'chat.completion.chunk','created':1,'model':'mock','choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':None}]}, {'id':'stream','object':'chat.completion.chunk','created':1,'model':'mock','choices':[],'usage':{'prompt_tokens':20,'completion_tokens':4,'total_tokens':24}}]
  return httpx.Response(200,headers={'content-type':'text/event-stream'},content=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n')
 return httpx.Response(200,json={'id':'one','object':'chat.completion','created':1,'model':'mock','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}})
client=OpenAI(api_key='test-only',base_url='https://unit.invalid/v1',http_client=httpx.Client(transport=httpx.MockTransport(respond)),max_retries=5)
reply=client.chat.completions.create(model='mock',messages=[{'role':'user','content':'fixture'}],max_tokens=1000,extra_body={'max_tokens':100000})
assert reply.choices[0].message.content=='ok' and seen[0]['max_tokens']==8192
stream=client.chat.completions.create(model='mock',messages=[],stream=True)
assert b.snapshot('daily')['resources']['model']['active']==1
try: client.chat.completions.create(model='mock',messages=[])
except UsageError as error: assert error.code=='quota_busy'
else: raise AssertionError('Concurrent model request bypassed budget')
assert len(list(stream))==2
assert b.snapshot('daily')['identity_usage']['input_tokens']==30
stream=client.chat.completions.create(model='mock',messages=[],stream=True)
stream.close()
assert b.snapshot('daily')['resources']['model']['uncertain']==1
try: client.chat.completions.create(model='failed',messages=[])
except Exception: pass
assert sum(x['model']=='failed' for x in seen)==1, 'SDK retried paid request without a reservation'
async def check_async():
 c=AsyncOpenAI(api_key='test-only',base_url='https://unit.invalid/v1',http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
 async with await c.chat.completions.create(model='mock',messages=[],stream=True) as stream:
  async for _ in stream: pass
 await c.close()
asyncio.run(check_async())
client.chat.completions.create(model='mock',messages=[])
count=len(seen)
try: client.chat.completions.create(model='mock',messages=[])
except UsageError as error: assert error.code=='quota_exhausted'
else: raise AssertionError('Exhausted budget reached network')
assert len(seen)==count==6
assert client.models.list().data==[]
assert len(seen)==6
view=b.snapshot('daily')
assert view['identity_usage']['input_tokens']==60 and view['cost'] is None
assert view['resources']['model']['active']==0
assert not reroute.exists(), 'Provider dotenv rerouted the durable usage ledger'
assert b.snapshot('other')['identity_usage']['calls']==0
print('guarded SDK requests:',len(seen))
'''
    result = subprocess.run([str(python), '-c', textwrap.dedent(script), str(Path(__file__).parents[1] / 'src'), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-4000:]
    assert 'guarded SDK requests: 6' in result.stdout


def test_installed_sdk_reserves_money_before_network_and_settles_cache_receipt(tmp_path):
    installed = Path(__file__).parents[1] / '.wearing/runtime/installed.json'
    if not installed.exists(): pytest.skip('Managed Hermes SDK is not installed')
    python = Path(json.loads(installed.read_text())['python'])
    if not python.is_file(): pytest.skip('Managed Hermes SDK interpreter unavailable')
    script = r'''
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import httpx
from openai import OpenAI
from openai._base_client import SyncAPIClient
from wearing.usage import UsageBook, UsageError
from wearing.usage_guard import wrap_sdk_request
b=UsageBook(Path(sys.argv[2]),enabled=True)
b.configure_pricing({'version':'synthetic-sdk-v1','currency':'CNY','budget':'2.10','models':[{'provider':'unit.invalid','model':'fixture','input_per_million':'2','cached_input_per_million':'0.2','output_per_million':'8','max_input_tokens':1000000,'max_output_tokens':8192}]})
seen=[]
def respond(request):
 body=json.loads(request.content); seen.append(body)
 assert b.snapshot('daily')['cost']['active_reserved_micros']==2065536
 if body.get('stream'):
  assert body['stream_options']['include_usage'] is True
  return httpx.Response(200,headers={'content-type':'text/event-stream'},content='data: [DONE]\n\n')
 return httpx.Response(200,json={'id':'one','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13,'prompt_cache_hit_tokens':8,'prompt_cache_miss_tokens':2}})
SyncAPIClient.request=wrap_sdk_request(SyncAPIClient.request,b,'daily')
c=OpenAI(api_key='test-only',base_url='https://unit.invalid/v1',http_client=httpx.Client(transport=httpx.MockTransport(respond)))
try: c.chat.completions.create(model='fixture',messages=[],n=2)
except UsageError as error: assert error.code=='quota_provider'
else: raise AssertionError('Multi-completion multiplied the reservation')
assert not seen and b.snapshot('daily')['resources']['model']['calls']==0
c.chat.completions.create(model='fixture',messages=[],max_tokens=99999,n=None)
assert seen[0]['max_tokens']==8192 and seen[0]['n']==1
assert b.snapshot('daily')['cost']['settled_estimate_micros']==30
stream=c.chat.completions.create(model='fixture',messages=[],stream=True,stream_options={'include_usage':False})
assert list(stream)==[]  # Complete transport with no usage is still uncertain.
view=b.snapshot('daily')
assert view['cost']['uncertain_reserved_micros']==2065536
assert view['resources']['model']['active']==0
try: c.chat.completions.create(model='fixture',messages=[])
except UsageError as error: assert error.code=='quota_budget'
else: raise AssertionError('Insufficient money reached the paid endpoint')
assert len(seen)==2
assert b.snapshot('daily')['resources']['model']['calls']==2
print('money admission and receipt passed')
'''
    result = subprocess.run([str(python), '-c', textwrap.dedent(script), str(Path(__file__).parents[1] / 'src'), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-4000:]
    assert 'money admission and receipt passed' in result.stdout


def test_installed_sdk_rejects_cross_origin_and_host_override_before_network_or_reservation(tmp_path):
    installed = Path(__file__).parents[1] / '.wearing/runtime/installed.json'
    if not installed.exists(): pytest.skip('Managed Hermes SDK is not installed')
    python = Path(json.loads(installed.read_text())['python'])
    if not python.is_file(): pytest.skip('Managed Hermes SDK interpreter unavailable')
    script = r'''
import sys,json,asyncio
from pathlib import Path
from typing import Any
sys.path.insert(0,sys.argv[1])
import httpx
from openai import OpenAI, AsyncOpenAI, APIStatusError
from openai._base_client import SyncAPIClient, AsyncAPIClient
from wearing.usage import UsageBook, UsageError
from wearing.usage_guard import wrap_sdk_request
b=UsageBook(Path(sys.argv[2]),enabled=True)
b.configure_pricing({'version':'synthetic-origin-v1','currency':'CNY','budget':'10','models':[{'provider':'unit.invalid','model':'fixture','input_per_million':'2','cached_input_per_million':'0.2','output_per_million':'8','max_input_tokens':1000000,'max_output_tokens':8192}]})
seen=[]
def respond(request):
 seen.append((str(request.url),request.headers.get('host'),request.headers.get('authorization')))
 if request.url.path.endswith('/redirect'):
  return httpx.Response(307,headers={'location':'https://other.invalid/models'})
 return httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':1}})
SyncAPIClient.request=wrap_sdk_request(SyncAPIClient.request,b,'daily')
AsyncAPIClient.request=wrap_sdk_request(AsyncAPIClient.request,b,'daily',asynchronous=True)
c=OpenAI(api_key='fixture-only',base_url='https://unit.invalid/v1',http_client=httpx.Client(transport=httpx.MockTransport(respond),follow_redirects=True))
body={'model':'fixture','messages':[]}
for url,headers in [
 ('https://other.invalid/v1/chat/completions',{}),
 ('http://unit.invalid/v1/chat/completions',{}),
 ('https://unit.invalid:444/v1/chat/completions',{}),
 ('https://other-user:other-password@unit.invalid/v1/chat/completions',{}),
 ('/chat/completions',{'Host':'other.invalid'}),
 ('/chat/completions',{'hOsT':'unit.invalid:444'}),
 ('/chat/completions',{'Host':'unit.invalid:not-a-port'}),
]:
 try: c.post(url,cast_to=dict[str,Any],body=body,options={'headers':headers})
 except UsageError as error: assert error.code=='quota_provider'
 else: raise AssertionError('Cross-provider request passed admission')
try: c.get('https://other.invalid/models',cast_to=dict[str,Any])
except UsageError as error: assert error.code=='quota_provider'
else: raise AssertionError('GET leaked provider credentials across origin')
async def check_async():
 ac=AsyncOpenAI(api_key='fixture-only',base_url='https://unit.invalid/v1',http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
 try: await ac.post('https://other.invalid/v1/chat/completions',cast_to=dict[str,Any],body=body)
 except UsageError as error: assert error.code=='quota_provider'
 else: raise AssertionError('Async cross-provider request passed admission')
 await ac.close()
asyncio.run(check_async())
assert not seen and b.snapshot('daily')['resources']['model']['calls']==0
# SDK-relative paths and same-origin absolute paths remain valid. Explicit
# default ports and hostname case must compare like the SDK HTTP destination.
c.post('/chat/completions',cast_to=dict[str,Any],body=body)
c.post('https://UNIT.INVALID:443/v1/chat/completions',cast_to=dict[str,Any],body=body,options={'headers':{'Host':'UNIT.INVALID:443'}})
assert len(seen)==2 and all(url=='https://unit.invalid/v1/chat/completions' for url,_,_ in seen)
assert all(auth=='Bearer fixture-only' for _,_,auth in seen)
view=b.snapshot('daily')
assert view['resources']['model']['calls']==2 and view['cost']['active_reserved_micros']==0
assert view['cost']['settled_estimate_micros']==56
# Even unmetered GETs must not follow a redirect into another provider/account.
try: c.get('/redirect',cast_to=dict[str,Any])
except APIStatusError as error: assert error.status_code==307
else: raise AssertionError('Provider redirect was followed')
assert len(seen)==3 and seen[-1][0]=='https://unit.invalid/v1/redirect'
assert b.snapshot('daily')['resources']['model']['calls']==2
assert 'fixture-only' not in b.path.read_bytes().decode('latin1')
c.close()
print('origin, Host and redirect guard passed')
'''
    result = subprocess.run([str(python), '-c', textwrap.dedent(script), str(Path(__file__).parents[1] / 'src'), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-4000:]
    assert 'origin, Host and redirect guard passed' in result.stdout
