"""Reuse Wearing's pinned native drivers through the official MCP client."""
import asyncio
from contextlib import AsyncExitStack
import json
import os
import secrets
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ... import android, computer, mobile
from ...runtime import HermesRuntime

from .schemas import COMPUTER_METHODS, COMPUTER_TOOLS
from ...config import write_private_json
from ...cloud.instance import read_private


class NativeAdapter:
    def __init__(self,data):
        self.data=Path(data).resolve()
        self.runtime=HermesRuntime(self.data)
        self.stack=AsyncExitStack()
        self.phone=None
        self.computer=None

    def computer_id(self):
        path = self.data / 'runtime/computer/connector-id.json'
        if path.exists():
            value = json.loads(read_private(path))['resource_id']
            import re
            if value != 'computer_local' and not re.fullmatch(r'computer_[a-f0-9]{20}', value):
                raise ValueError('invalid_local_computer_id')
            return value
        value = 'computer_' + secrets.token_hex(10)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        from filelock import FileLock
        with FileLock(str(path) + '.lock'):
            if path.exists():
                return json.loads(read_private(path))['resource_id']
            write_private_json(path, {'resource_id':value})
        return value

    def verify_binding(self, specs, local):
        resources = {r['resource_id']:r for r in local}
        # The first installed connector used the local driver's legacy ID.
        computer_spec = next((r for r in local if r['kind']=='computer'), None)
        if computer_spec:
            resources['computer_local'] = computer_spec
        for r in specs:
            v = resources.get(r.resource_id)
            if not v or v['kind'] != r.kind or not r.methods <= set(v['methods']):
                raise ValueError('配对文件的设备或权限与本机不符，请重新导出本机清单。')

    async def __aenter__(self):
        await self.stack.__aenter__()
        return self

    async def __aexit__(self,*args):
        return await self.stack.__aexit__(*args)

    async def session(self,script):
        env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','USER','TEMP','TMP','TMPDIR','SystemRoot','LOCALAPPDATA'}}
        env.update(HERMES_HOME=str(self.runtime.home),HERMES_RUNTIME_DIR=str(self.runtime.root/'tools'),
                   PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
        if script=='computer_proxy.py':env['HERMES_INTERACTIVE']='1'
        log=await self.stack.enter_async_context(_devnull())
        read,write=await self.stack.enter_async_context(stdio_client(StdioServerParameters(
            command=str(self.runtime.python),args=[str(Path(__file__).resolve().parents[2]/script),str(self.data)],env=env),errlog=log))
        client=await self.stack.enter_async_context(ClientSession(read,write))
        await client.initialize()
        return client

    async def phone_session(self):
        if self.phone is None: self.phone=await self.session('phone_proxy.py')
        return self.phone

    async def computer_session(self):
        if self.computer is None: self.computer=await self.session('computer_proxy.py')
        return self.computer

    async def inventory(self):
        records=mobile.registry(self.data)['devices']
        resources=[{'resource_id':rid,'name':r.get('name','Android'),'kind':'android',
            'methods':['phone.'+name for name in mobile.TOOLS+('mobile_set_text',)]}
            for rid,r in records.items() if r['enabled']]
        tools=[]
        if resources:
            tools=[t.model_dump(mode='json',by_alias=True) for t in (await (await self.phone_session()).list_tools()).tools if t.name!='mobile_list_devices']
        if computer.enrolled(self.data):
            resources.append({'resource_id':self.computer_id(),'name':'这台电脑','kind':'computer','methods':list(COMPUTER_METHODS)})
            tools+=COMPUTER_TOOLS
        return {'resources':resources,'tools':tools}

    async def availability(self,specs):
        # Heartbeats only need transport state, not three getprop calls per phone.
        # One slow phone must not postpone the heartbeat for all other resources.
        from ...doctor import parse_adb_devices, run_readonly
        adb=android.adb_path(self.runtime.root)
        code,output=await asyncio.to_thread(run_readonly,[adb,'devices','-l'],timeout=5) if adb else (1,'')
        connected={r['serial'] for r in parse_adb_devices(output) if r['state']=='device'} if not code else set()
        records=mobile.registry(self.data)['devices']
        out={}
        for r in specs:
            rid=r['resource_id']
            if r['kind']=='android':
                record=records.get(rid,{})
                out[rid]=bool(record.get('enabled') and record.get('serial') in connected)
            else:
                probe=await self.runtime.computer_command('control')
                # Upstream controls are re-read immediately before native observations.
                out[rid]=bool(computer.enrolled(self.data) and probe.get('holder')=='agent')
        return out

    async def execute(self,command,approval=None):
        rid=command.resource_id
        if command.method.startswith('phone.'):
            name=command.method[6:]
            if name not in mobile.TOOLS+('mobile_set_text',): raise ValueError('phone_method_not_allowed')
            args={**command.params,'resource_id':rid}
            result=await (await self.phone_session()).call_tool(name,args)
            if not mobile.registry(self.data)['devices'].get(rid,{}).get('enabled'):
                raise ValueError('phone_taken_over_during_action')
        elif command.method in COMPUTER_METHODS and rid in ('computer_local', self.computer_id()):
            if command.method=='computer.input':
                if approval is None or not approval.permits(command):raise ValueError('desktop_approval_required')
                params={k:v for k,v in command.params.items() if k!='approval_id'}
                result=await (await self.computer_session()).call_tool('wearing_computer_input',{'action':params,'approval':approval.model_dump(mode='json')})
            else:
                action='status' if command.method=='computer.status' else command.params.get('action')
                if action not in ('status','list_apps','list_windows','capture'): raise ValueError('computer_action_not_allowed')
                result=await (await self.computer_session()).call_tool('wearing_computer_observe',{**command.params,'resource_id':'computer_local','action':action})
        else: raise ValueError('device_method_not_allowed')
        return result.model_dump(mode='json',by_alias=True)


from contextlib import asynccontextmanager
@asynccontextmanager
async def _devnull():
    with open(os.devnull,'w') as stream: yield stream
