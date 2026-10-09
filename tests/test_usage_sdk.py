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
