"""Official SDK stdio handshake and calls, separate from relay HTTP tests."""
import os
import asyncio
from pathlib import Path
import sys
from contextlib import AsyncExitStack

import pytest
mcp=pytest.importorskip('mcp')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import instance_relay, PairRequest
from wearing.cloud.device_permissions import ApplyPermission, ChangePermission, create_permission, apply_permission
from wearing.cloud.device_setup import tools_for
from wearing.config import write_private_json


@pytest.mark.asyncio
async def test_private_remote_proxy_registers_standard_schemas_and_calls(tmp_path):
    root=tmp_path/'instance';initialize_instance(root,'tenant_alice','http://127.0.0.1:18865')
    write_private_json(root/'data/remote-devices.json', {'schema_version': 1, 'enabled': True})
    store=instance_relay(root)
    schema={'name':'mobile_press_button','description':'test','inputSchema':{'type':'object','properties':{'resource_id':{'type':'string'},'button':{'type':'string'}},'required':['resource_id','button']}}
    spec={'resource_id':'phone_test','name':'Phone','kind':'android','methods':['phone.mobile_press_button']}
    b=store.pair_code('daily',[spec],[schema]);store.pair(PairRequest(code=b['code'],token='a'*64))
    script=Path(__file__).resolve().parents[1]/'src/wearing/remote_proxy.py'
    async with AsyncExitStack() as stack:
        log=stack.enter_context(open(tmp_path/'mcp-stderr.log','w'))
        read,write=await stack.enter_async_context(stdio_client(StdioServerParameters(command=sys.executable,args=[str(script),str(root),'daily']),errlog=log))
        client=await stack.enter_async_context(ClientSession(read,write));await client.initialize()
        tools=(await client.list_tools()).tools
        assert {t.name for t in tools}=={'mobile_press_button','wearing_list_devices'}
        tool=next(t for t in tools if t.name=='mobile_press_button')
        assert 'enum' not in tool.model_dump(by_alias=True)['inputSchema']['properties']['resource_id']
        inventory=await client.call_tool('wearing_list_devices',{})
        assert not inventory.isError and 'phone_test' in inventory.content[0].text
        result=await client.call_tool('mobile_press_button',{'resource_id':'phone_test','button':'HOME'})
        assert result.isError and 'device_not_available' in result.content[0].text
        # Newly paired devices are selected from live inventory. Actual grant
        # enforcement survives a schema cached by the engine before enrollment.
        second={**spec,'resource_id':'phone_second'}
        b=store.pair_code('daily',[second],[schema]);store.pair(PairRequest(code=b['code'],token='b'*64))
        assert 'phone_second' in (await client.call_tool('wearing_list_devices',{})).content[0].text
        result=await client.call_tool('mobile_press_button',{'resource_id':'phone_second','button':'HOME'})
        assert result.isError and 'device_not_available' in result.content[0].text
        result=await client.call_tool('mobile_press_button',{'resource_id':'phone_forged','button':'HOME'})
        assert result.isError and 'device_not_available' in result.content[0].text


@pytest.mark.asyncio
async def test_permission_change_notifies_existing_mcp_session_and_removes_downgraded_tools(tmp_path):
    root=tmp_path/'instance';initialize_instance(root,'tenant_alice','http://127.0.0.1:18865')
    write_private_json(root/'data/remote-devices.json', {'schema_version': 1, 'enabled': True})
    store=instance_relay(root)
    write_private_json(root/'data/device-endpoint.json',{'endpoint':'https://relay.example','ca_pem':'test'})
    spec={'resource_id':'computer_test','kind':'computer','name':'测试电脑','methods':['computer.status','computer.observe']}
    b=store.pair_code('daily',[spec],tools_for([spec]));store.pair(PairRequest(code=b['code'],token='a'*64))
    script=Path(__file__).resolve().parents[1]/'src/wearing/remote_proxy.py'
    changed=asyncio.Event()
    from mcp import types
    async def notification(message):
        if isinstance(message,types.ServerNotification) and isinstance(message.root,types.ToolListChangedNotification):changed.set()
    async with AsyncExitStack() as stack:
        log=stack.enter_context(open(tmp_path/'mcp-stderr.log','w'))
        read,write=await stack.enter_async_context(stdio_client(StdioServerParameters(command=sys.executable,args=[str(script),str(root),'daily']),errlog=log))
        client=await stack.enter_async_context(ClientSession(read,write,message_handler=notification))
        initialized=await client.initialize();assert initialized.capabilities.tools.listChanged
        assert {t.name for t in (await client.list_tools()).tools}=={'wearing_list_devices','wearing_computer_observe'}
        def update(mode,request_id):
            bundle=create_permission(store,root,'daily',ChangePermission(request_id=request_id,
                resource_id='computer_test',revision=store.inventory('daily')[0]['permission_revision'],mode=mode))
            apply_permission(store,'a'*64,ApplyPermission(**{k:bundle[k] for k in ('request_id','code','digest')}))
        update('input','b'*32)
        await asyncio.wait_for(changed.wait(),8)
        assert 'wearing_computer_request_input' in {t.name for t in (await client.list_tools()).tools}
        changed.clear();update('observe','c'*32)
        await asyncio.wait_for(changed.wait(),8)
        assert {t.name for t in (await client.list_tools()).tools}=={'wearing_list_devices','wearing_computer_observe'}
        result=await client.call_tool('wearing_computer_request_input',{'resource_id':'computer_test'})
        assert result.isError and result.content[0].text=='device_tool_not_granted'


@pytest.mark.asyncio
async def test_first_enrollment_and_private_gate_are_live_in_one_mcp_session(tmp_path):
    root=tmp_path/'instance';initialize_instance(root,'tenant_alice','http://127.0.0.1:18865')
    store=instance_relay(root)
    script=Path(__file__).resolve().parents[1]/'src/wearing/remote_proxy.py'
    flag=root/'data/remote-devices.json'
    async with AsyncExitStack() as stack:
        log=stack.enter_context(open(tmp_path/'mcp-stderr.log','w'))
        read,write=await stack.enter_async_context(stdio_client(StdioServerParameters(
            command=sys.executable,args=[str(script),str(root),'daily']),errlog=log))
        client=await stack.enter_async_context(ClientSession(read,write));await client.initialize()
        assert not (await client.list_tools()).tools
        # Even the inventory endpoint must not bypass an absent/unsafe gate.
        async def denied():
            assert not (await client.list_tools()).tools
            result=await client.call_tool('wearing_list_devices',{})
            assert result.isError and result.content[0].text=='device_tool_not_granted'
            result=await client.call_tool('wearing_computer_observe',{'resource_id':'computer_test'})
            assert result.isError and result.content[0].text=='device_tool_not_granted'
        await denied()
        spec={'resource_id':'computer_test','kind':'computer','name':'测试电脑','methods':['computer.status','computer.observe']}
        bundle=store.pair_code('daily',[spec],tools_for([spec]));store.pair(PairRequest(code=bundle['code'],token='a'*64))
        await denied()  # pairing alone cannot enable the private authority
        write_private_json(flag,{'schema_version':1,'enabled':True})
        assert {t.name for t in (await client.list_tools()).tools}=={'wearing_list_devices','wearing_computer_observe'}
        other={**spec,'resource_id':'computer_other'}
        bundle=store.pair_code('work',[other],tools_for([other]));store.pair(PairRequest(code=bundle['code'],token='b'*64))
        inventory=await client.call_tool('wearing_list_devices',{})
        assert 'computer_test' in inventory.content[0].text and 'computer_other' not in inventory.content[0].text
        for value in ({'schema_version':1,'enabled':False},{'schema_version':True,'enabled':True},
                      {'schema_version':1,'enabled':1},{'schema_version':1,'enabled':True,'extra':1}):
            write_private_json(flag,value);await denied()
        flag.write_text('{');await denied()
        write_private_json(flag,{'schema_version':1,'enabled':True})
        if os.name!='nt':
            flag.chmod(0o644);await denied();flag.chmod(0o600)
        assert len((await client.list_tools()).tools)==2
        flag.unlink();await denied()
        alternative=root/'valid.json';write_private_json(alternative,{'schema_version':1,'enabled':True})
        flag.symlink_to(alternative);await denied()
