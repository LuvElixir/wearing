"""Cloud Hermes MCP client of its own private device outbox, not a device driver."""
import asyncio
import json
from pathlib import Path
import sys
import time

from mcp import types
from mcp.server.lowlevel import NotificationOptions
from mcp.server.stdio import stdio_server

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wearing.cloud.relay import instance_relay, RelayError
from wearing.mcp_server import create_server


def tool_schemas(store,identity):
    specs=store.inventory(identity)
    ids={r['resource_id'] for r in specs}
    schemas={}
    from wearing.connectors.remote.schemas import COMPUTER_TOOLS
    computer_schemas={t['name']:t for t in COMPUTER_TOOLS}
    for schema in store.schemas(identity):
        if schema.get('name') in computer_schemas:schema=computer_schemas[schema['name']]
        tool=types.Tool.model_validate(schema)
        if tool.name not in schemas:
            value=tool.model_dump(mode='json',by_alias=True)
            allowed=[r['resource_id'] for r in specs if
                     (bool({'computer.observe','computer.status'}.intersection(r['methods'])) if tool.name=='wearing_computer_observe' else
                      'computer.input' in r['methods'] if tool.name.startswith('wearing_computer_') else 'phone.'+tool.name in r['methods'])]
            if not allowed: continue
            # Hermes caches schemas at boot. Resolve the current grant at execution,
            # so another phone of an existing kind works without stale ID enums.
            value['inputSchema']['properties']['resource_id']={'type':'string',
                'description':'先调用 wearing_list_devices，选择当前身份已接入的 resource_id。'}
            schemas[tool.name]=types.Tool.model_validate(value)
    schemas['wearing_list_devices']=types.Tool(name='wearing_list_devices',description='查看这个身份已配对的电脑和手机及当前在线状态。',
        inputSchema={'type':'object','properties':{},'additionalProperties':False})
    return list(schemas.values())


async def serve(root,identity):
    store=instance_relay(root)
    session=None
    signature=None
    session_grant=None
    grant_session=None
    def current_tools():
        tools=tool_schemas(store,identity)
        return tools,json.dumps([t.model_dump(mode='json',by_alias=True) for t in tools],sort_keys=True)
    async def list_tools(context,params):
        nonlocal session,signature
        if context is not None:session=context.session
        tools,signature=current_tools()
        return types.ListToolsResult(tools=tools)

    async def notify_changes():
        nonlocal signature
        while True:
            await asyncio.sleep(2)
            if session is None:continue
            _,latest=current_tools()
            if latest!=signature:
                try:
                    await session.send_tool_list_changed()
                    signature=latest
                except (RuntimeError,OSError):
                    pass  # transport teardown: next session lists the current grant

    async def call_tool(context,params):
        nonlocal session_grant,grant_session
        args=params.arguments or {}
        if params.name=='wearing_list_devices':
            return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(store.inventory(identity),ensure_ascii=False))])
        if params.name not in {t.name for t in tool_schemas(store,identity)}:
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='device_tool_not_granted')])
        try:
            if params.name in ('wearing_computer_request_input','wearing_computer_input_result'):
                from wearing.cloud.desktop_approval import InputProposal, propose, list_proposals
                if params.name=='wearing_computer_request_input':
                    from wearing.cloud.desktop_runs import request_and_wait
                    value=propose(store,identity,InputProposal.model_validate(args),for_run=True)
                    value=await request_and_wait(store,identity,value,context,
                        session_grant=session_grant if grant_session is context.session else None)
                    if value.get('state')=='completed' and value.get('task_grant_id'):
                        session_grant=value['task_grant_id'];grant_session=context.session
                else:
                    value=next((r for r in list_proposals(store,identity) if r['approval_id']==args.get('approval_id') and r['resource_id']==args.get('resource_id')),None)
                    if not value:raise RelayError('command_not_found')
                    if value['command_id']:value['receipt']=store.read_result(value['command_id'],identity)
                return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(value,ensure_ascii=False))])
            payload={k:v for k,v in args.items() if k!='resource_id'}
            method=('computer.status' if payload.get('action')=='status' else 'computer.observe') if params.name=='wearing_computer_observe' else 'phone.'+params.name
            command=store.enqueue(identity,args.get('resource_id'),method,payload)
            deadline=time.monotonic()+65
            while time.monotonic()<deadline:
                result=store.read_result(command.command_id,identity)
                if result['state'] in ('completed','device_error') and result['result']:
                    return types.CallToolResult.model_validate(result['result'])
                if result['state'] not in ('queued','executing'):
                    break
                await asyncio.sleep(.25)
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='device_result_unknown: 操作未得到完整结果。不要重复动作，先重新观察屏幕或请用户核对。')])
        except RelayError as error:
            if error.code=='desktop_workflow_stopped':
                return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='desktop_workflow_stopped: 本轮电脑操作的确认已拒绝、过期或取消。停止操作及重新申请，等用户重新交代任务。')])
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='device_not_available: 设备离线、被接管、正在使用或当前身份没有授权；尚未派发新操作。')])
        except (ValueError,TypeError):
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='device_not_available: 设备离线、被接管、正在使用或当前身份没有授权；尚未派发新操作。')])
        except asyncio.CancelledError:
            if 'command' in locals():
                store.cancel(command.command_id,identity)
            raise
    server=create_server('wearing-remote-devices',list_tools,call_tool)
    async with stdio_server() as (read,write):
        watcher=asyncio.create_task(notify_changes())
        try:
            await server.run(read,write,server.create_initialization_options(NotificationOptions(tools_changed=True)))
        finally:
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)


if __name__=='__main__':
    asyncio.run(serve(Path(sys.argv[1]).resolve(),sys.argv[2]))
