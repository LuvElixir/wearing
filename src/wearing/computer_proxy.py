"""Pinned upstream desktop driver, preserving its standard approval/lease gates."""
import asyncio
import base64
import json
from pathlib import Path
import sys

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wearing.connectors.remote.schemas import COMPUTER_TOOLS
from wearing.computer import enrolled
from wearing.mcp_server import create_server
from wearing.desktop_input import DesktopFrames, DesktopAction, DesktopApproval
from wearing.desktop_capture import capture_with_text
from wearing.device_gateway import DeviceGateway


def fenced_dispatch(dispatch, gateway, resource):
    def run(args):
        permit = gateway.permit_agent(resource)
        with gateway.native_lock(resource):
            gateway.validate_agent(permit)
            result = dispatch(args)
            gateway.validate_agent(permit)
            return result
    return run


async def serve(data):
    from wearing.runtime import HermesRuntime
    from wearing.native_runtime import driver_runtime
    _, source = driver_runtime(HermesRuntime(data))
    sys.path.insert(0,str(source))
    from tools.bot_desktop import lease
    session='wearing-remote-desktop'
    if sys.platform.startswith('linux'):
        from wearing.linux_computer import LinuxComputerBackend
        backend = LinuxComputerBackend()
        dispatch, computer_use_status, set_approval_callback = backend.dispatch, backend.status, backend.set_approval_callback
        release_computer_use_session = lambda _: None
    else:
        from tools.computer_use.tool import handle_computer_use, release_computer_use_session, set_approval_callback, _backend_for_call
        from tools.computer_use.permissions import computer_use_status
        from tools.computer_use.cua_backend_capture import _tree_and_title
        dispatch = lambda args:capture_with_text(args,handle_computer_use,_backend_for_call,_tree_and_title,session)
    resource_path = data / 'runtime/computer/connector-id.json'
    resource = json.loads(resource_path.read_text())['resource_id'] if resource_path.exists() else 'computer_local'
    gateway = DeviceGateway()
    frames=DesktopFrames(fenced_dispatch(dispatch, gateway, resource),lease,set_approval_callback)

    async def list_tools(context,params):
        native={'name':'wearing_computer_input','description':'Internal connector transport of one user-approved action.',
                'inputSchema':{'type':'object','properties':{'action':DesktopAction.model_json_schema(),'approval':DesktopApproval.model_json_schema()},
                    'required':['action','approval'],'additionalProperties':False}}
        return types.ListToolsResult(tools=[types.Tool.model_validate(COMPUTER_TOOLS[0]),types.Tool.model_validate(native)])

    async def call_tool(context,params):
        args=params.arguments or {}
        if params.name not in ('wearing_computer_observe','wearing_computer_input') or (params.name=='wearing_computer_observe' and args.get('resource_id')!='computer_local'):
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='computer_not_paired')])
        if not enrolled(data):
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='computer_not_enrolled')])
        action=args.get('action')
        if params.name=='wearing_computer_observe' and (action not in ('status','list_apps','list_windows','capture') or set(args)-{'resource_id','action','app','window_id','pid'}
                or (('window_id' in args)!=('pid' in args))
                or ('window_id' in args and (action!='capture' or type(args['window_id']) is not int or args['window_id']<0
                    or type(args['pid']) is not int or args['pid']<1))):
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='computer_action_not_allowed')])
        try:
            lease.assert_agent_may_act()
            gateway.permit_agent(resource)
            meta=None
            if params.name=='wearing_computer_input':
                if set(args)!={'action','approval'}:raise ValueError('desktop_input_shape')
                result=await asyncio.to_thread(frames.act,args['action'],args['approval'])
            elif action=='status':
                result=computer_use_status()
                result['control']=lease.public_view(lease.get())
                return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(result))])
            else:
                payload={'action':action,'mode':'ax'}
                if args.get('app'): payload['app']=args['app']
                if 'window_id' in args:payload['window_id']=args['window_id']
                if 'pid' in args:payload['pid']=args['pid']
                result,meta=await asyncio.to_thread(frames.observe,payload)
            metadata=[types.TextContent(type='text',text=json.dumps(meta,ensure_ascii=False))] if meta else []
            if isinstance(result,str):
                value=json.loads(result)
                screenshot=value.pop('screenshot',None)
                if screenshot:
                    if screenshot.get('mime_type')!='image/png':raise ValueError('invalid_native_capture')
                    return types.CallToolResult(isError=bool(value.get('error') or value.get('ok') is False),content=metadata+[
                        types.TextContent(type='text',text=json.dumps(value,ensure_ascii=False)),
                        types.ImageContent(type='image',mimeType='image/png',data=screenshot['data'])])
                return types.CallToolResult(isError=bool(value.get('error') or value.get('ok') is False),
                    content=metadata+[types.TextContent(type='text',text=result)])
            content=metadata
            for block in result.get('content',[]):
                if block.get('type')=='text':
                    content.append(types.TextContent(type='text',text=block['text']))
                elif block.get('type')=='image_url':
                    url=block['image_url']['url']
                    if not url.startswith('data:image/png;base64,'): raise ValueError('invalid_native_capture')
                    content.append(types.ImageContent(type='image',mimeType='image/png',data=url.split(',',1)[1]))
            return types.CallToolResult(content=content or [types.TextContent(type='text',text=result.get('text_summary',''))])
        except Exception:
            return types.CallToolResult(isError=True,content=[types.TextContent(type='text',text='desktop_action_unavailable_or_stale_or_taken_over: 请重新读取指定应用；不要重做结果不明的操作。')])

    server=create_server('wearing-computer-observe',list_tools,call_tool)
    try:
        async with stdio_server() as (read,write):
            await server.run(read,write,server.create_initialization_options())
    finally:
        release_computer_use_session(session)


if __name__=='__main__':
    asyncio.run(serve(Path(sys.argv[1]).resolve()))
