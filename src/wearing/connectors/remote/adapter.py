"""Reuse Wearing's pinned native drivers through the official MCP client."""
import asyncio
from contextlib import AsyncExitStack
import json
import inspect
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
from ...device_gateway import DeviceGateway, GatewayScope, GatewayError


class NativeAdapter:
    def __init__(self,data, *, private_gateway=None, private_media=None):
        self.data=Path(data).resolve()
        self.runtime=HermesRuntime(self.data)
        self.stack=AsyncExitStack()
        self.phone=None
        self.computer=None
        # Only trusted host composition can inject these; neither paired
        # metadata nor a cloud request enables an unisolated private viewer.
        self._gateway = private_gateway
        self.private_media = private_media
        host_config = self.data / 'runtime/private-media.json'
        if self._gateway is None and self.private_media is None and host_config.exists():
            from ...private_media_client import PrivateMediaClient
            self.private_media = PrivateMediaClient.from_path(host_config)
            self._gateway = self.private_media.gateway()

    @property
    def gateway(self):
        if self._gateway is None:
            self._gateway = DeviceGateway()
        return self._gateway

    @property
    def human_access_ready(self):
        return bool(self._gateway is not None and self._gateway.private_access_ready and self.private_media is not None)

    def recover_human_access(self, resources):
        if self._gateway is not None or (Path.home() / '.wearing/device-gateway/ownership.sqlite3').exists():
            self.gateway.recover(resources)

    async def apply_human_control(self, control, scope):
        current = self.gateway.snapshot(scope.resource_id)
        session = control['session_id']
        action = control['action']
        if action == 'takeover' and self.human_access_ready:
            if current['session_id'] != session:
                current = self.gateway.begin_human(scope, session, expected_epoch=current['epoch'])
            if current['state'] == 'handoff_pending':
                current = self.gateway.activate_human(scope, session, current['epoch'])
            elif current['state'] == 'paused':
                # Reconnect/restart cannot resurrect a human session. Tell the
                # cloud it needs a new explicit request instead of retrying.
                current = self.gateway.pause(scope, session, current['epoch'])
            elif current['state'] == 'human_private':
                # This directive arrived through authenticated connector poll.
                # Viewer heartbeats alone cannot extend server authority.
                current = self.gateway.renew_human(scope, session, current['epoch'])
            elif current['state'] != 'human_private':
                raise GatewayError('human_session_not_active')
        elif current['session_id'] == session and action == 'return' and self.human_access_ready:
            if current['state'] != 'agent_ready':
                if control.get('safe_screen_confirmed') is not True or control.get('scope_confirmed') is not True:
                    raise GatewayError('human_return_confirmation_required')
                current = self.gateway.prepare_return(scope, session, current['epoch'])
                try:
                    cleared = self.private_media.clear(scope, session)
                    if inspect.isawaitable(cleared):
                        cleared = await cleared
                except Exception:
                    cleared = False
            else:
                cleared = True  # Idempotent lost-ACK replay never clears twice.
            current = self.gateway.finish_human(scope, session, current['epoch'],
                safe_screen_confirmed=control.get('safe_screen_confirmed') is True,
                scope_confirmed=control.get('scope_confirmed') is True,
                clear_media=lambda: cleared is True)
        elif current['session_id'] == session:
            current = self.gateway.pause(scope, session, current['epoch'])
        else:
            raise GatewayError('human_session_not_active')
        return {'session_id':session, 'epoch':control['epoch'], 'revision':control['revision'],
                'gateway_epoch':current['epoch'], 'state':current['state']}

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
        from ...native_runtime import driver_runtime
        interpreter, _ = driver_runtime(self.runtime)
        env={k:v for k,v in os.environ.items() if k in {'HOME','PATH','USER','TEMP','TMP','TMPDIR','SystemRoot','LOCALAPPDATA'}}
        if os.name=='posix' and __import__('sys').platform.startswith('linux'):
            # Values belong to the trusted execution-service startup, never to
            # paired metadata or an agent command.
            env.update({k:os.environ[k] for k in ('DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS') if k in os.environ})
        env.update(HERMES_HOME=str(self.runtime.home),HERMES_RUNTIME_DIR=str(self.runtime.root/'tools'),
                   PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
        if script=='computer_proxy.py':env['HERMES_INTERACTIVE']='1'
        log=await self.stack.enter_async_context(_devnull())
        read,write=await self.stack.enter_async_context(stdio_client(StdioServerParameters(
            command=str(interpreter),args=[str(Path(__file__).resolve().parents[2]/script),str(self.data)],env=env),errlog=log))
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
        from ...device_files_native import advertised
        for resource in resources:
            resource['methods'] += await asyncio.to_thread(advertised, resource['resource_id'])
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
                if (self.runtime.root/'native-driver.json').exists():
                    from ...native_runtime import driver_runtime
                    interpreter, source = driver_runtime(self.runtime)
                    process = await asyncio.create_subprocess_exec(str(interpreter),
                        str(Path(__file__).resolve().parents[2]/'computer_bridge.py'), str(source), 'control',
                        env=self.runtime.env(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                    try:
                        output, _ = await asyncio.wait_for(process.communicate(), 8)
                        probe=json.loads(output) if process.returncode==0 else {}
                    finally:
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                else:
                    probe=await self.runtime.computer_command('control')
                # Upstream controls are re-read immediately before native observations.
                out[rid]=bool(computer.enrolled(self.data) and probe.get('holder')=='agent')
        return out

    async def execute(self,command,approval=None):
        rid=command.resource_id
        if command.method.startswith('phone.'):
            gateway = self.gateway
            permit = gateway.permit_agent(rid)
            name=command.method[6:]
            if name not in mobile.TOOLS+('mobile_set_text',): raise ValueError('phone_method_not_allowed')
            args={**command.params,'resource_id':rid}
            result=await (await self.phone_session()).call_tool(name,args)
            gateway.validate_agent(permit)
            if not mobile.registry(self.data)['devices'].get(rid,{}).get('enabled'):
                raise ValueError('phone_taken_over_during_action')
        elif command.method in COMPUTER_METHODS and rid in ('computer_local', self.computer_id()):
            permit = self.gateway.permit_agent(rid)
            if command.method=='computer.input':
                if approval is None or not approval.permits(command):raise ValueError('desktop_approval_required')
                params={k:v for k,v in command.params.items() if k!='approval_id'}
                result=await (await self.computer_session()).call_tool('wearing_computer_input',{'action':params,'approval':approval.model_dump(mode='json')})
            else:
                action='status' if command.method=='computer.status' else command.params.get('action')
                if action not in ('status','list_apps','list_windows','capture'): raise ValueError('computer_action_not_allowed')
                result=await (await self.computer_session()).call_tool('wearing_computer_observe',{**command.params,'resource_id':'computer_local','action':action})
            self.gateway.validate_agent(permit)
        else: raise ValueError('device_method_not_allowed')
        return result.model_dump(mode='json',by_alias=True)

    async def human_availability(self, specs, physical):
        if not self.human_access_ready:
            return {}
        check = getattr(self.private_media,'availability',None)
        media = await check(specs) if callable(check) else physical
        return {r['resource_id']:bool(media.get(r['resource_id']) and
                (physical.get(r['resource_id']) or r['kind']=='computer')) for r in specs
                if r['kind'] in ('android','computer')}


from contextlib import asynccontextmanager
@asynccontextmanager
async def _devnull():
    with open(os.devnull,'w') as stream: yield stream
