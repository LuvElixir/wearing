import json
from pathlib import Path
import subprocess

import pytest
import yaml

from wearing import android, mobile
from wearing.config import write_private_json
from wearing.profile import prepare_profile
from wearing.runtime import HermesRuntime, RuntimeError


async def test_phone_binding_requires_authorized_selected_device(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    monkeypatch.setattr(mobile, "installed", lambda root: {"version": mobile.VERSION})
    monkeypatch.setattr(android, "devices", lambda root: {"state": "checked", "devices": [
        {"serial": "waiting", "model": "Phone A", "state": "unauthorized"},
        {"serial": "ready", "model": "Phone B", "state": "device", "android_version": "9"}], "usb": []})
    with pytest.raises(RuntimeError, match="授权"):
        await runtime.bind_phone("waiting")
    with pytest.raises(RuntimeError, match="授权"):
        await runtime.bind_phone("unlisted")
    await runtime.bind_phone("ready")
    assert mobile.binding(tmp_path)["serial"] == "ready"
    assert (await runtime.phone_status())["selected_online"]
    runtime.pause_phone()
    assert mobile.binding(tmp_path)["enabled"] is False
    # Disconnecting the chosen phone must not select another authorized device.
    monkeypatch.setattr(android, "devices", lambda root: {"state": "checked", "devices": [
        {"serial": "another", "model": "Phone C", "state": "device"}], "usb": []})
    assert not (await runtime.phone_status())["selected_online"]
    assert mobile.binding(tmp_path)["serial"] == "ready"


def test_phone_profile_keeps_only_explicit_connectors_active(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write_private_json(home / "config.yaml", {"mcp_servers": {"unrelated": {"command": "keep-me"}}})
    files, phone = {"command": "files"}, {"command": "phone"}
    result = prepare_profile(home, tmp_path / "source", files, phone)
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert result["toolsets"] == ["memory", "session_search", "web", "todo", "skills", "vision", "wearing_files", "wearing_phone"]
    assert config["platform_toolsets"]["api_server"] == result["toolsets"]
    assert config["platform_toolsets"]["cli"] == ["no_mcp"]
    assert config["mcp_servers"]["unrelated"] == {"command": "keep-me"}
    prepare_profile(home, tmp_path / "source", files)
    assert yaml.safe_load((home / "config.yaml").read_text())["platform_toolsets"]["api_server"] == ["memory", "session_search", "web", "todo", "skills", "vision", "wearing_files"]


def test_real_mobile_proxy_scopes_schemas_and_blocks_before_device_access(tmp_path):
    """Real MCP protocol, installed driver, synthetic binding; never calls a phone."""
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    package = mobile.installed(runtime.root)
    if not runtime.python.is_file() or not package:
        pytest.skip("Prepare the pinned mobile connector to run this integration contract")
    directory = tmp_path / "runtime/mobile"
    directory.mkdir(parents=True)
    (directory / "node_modules").symlink_to(runtime.root / "mobile/node_modules", target_is_directory=True)
    write_private_json(directory / "installed.json", package)
    write_private_json(tmp_path / "phone.json", {"serial": "synthetic-device", "enabled": True})
    script = tmp_path / "check.py"
    android_dir = tmp_path / "runtime/android"
    android_dir.mkdir()
    (android_dir / "platform-tools").symlink_to(runtime.root / "android/platform-tools", target_is_directory=True)
    script.write_text('''
import asyncio, json, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
async def main():
    root=Path(sys.argv[1])
    sys.path.insert(0,str(Path(sys.argv[2]).parent))
    import phone_proxy as proxy
    from unittest.mock import patch
    from phone_proxy import normalize_result, DeviceLock, lock_path, prepare_arguments, current_binding
    from mobile import registry, resource_id
    first=resource_id('synthetic-device')
    second=resource_id('second-device')
    data=registry(root)
    data['devices'][second]={'serial':'second-device','resource_id':second,'name':'Another phone','platform':'android','enabled':True}
    (root/'phone.json').write_text(json.dumps(data))
    assert prepare_arguments('mobile_get_screen_size',{'resource_id':first},current_binding(root,first)['serial'])=={'device':'synthetic-device'}
    assert prepare_arguments('mobile_get_screen_size',{'resource_id':second},current_binding(root,second)['serial'])=={'device':'second-device'}
    reads=[]
    class Reader:
        async def call_tool(self, name, args):
            reads.append('legacy')
            return types.CallToolResult(content=[types.TextContent(type='text',text='legacy')])
    for ok in (True,False):
        async def native(command,env,payload,timeout):
            assert timeout==15 and json.loads(payload)=={'serial':'synthetic-device','operation':'observe'}
            reads.append('native')
            return json.dumps({'ok':ok,'elements':[]}).encode()
        reads.clear()
        with patch.object(proxy,'u2_installed',return_value=True),patch.object(proxy,'run_child',native):
            result=await proxy.read_screen(Reader(),{'device':'synthetic-device'},root,current_binding(root,first),{})
        assert result.is_error == (not ok) and reads==['native']
    reads.clear()
    with patch.object(proxy,'u2_installed',return_value=False):
        result=await proxy.read_screen(Reader(),{'device':'synthetic-device'},root,current_binding(root,first),{})
    assert not result.is_error and reads==['legacy']
    data['devices'][first]['enabled']=False
    (root/'phone.json').write_text(json.dumps(data))
    with patch.object(proxy,'u2_installed',return_value=True):
        try:
            await proxy.read_screen(Reader(),{},root,data['devices'][first],{})
            raise AssertionError('paused native read was allowed')
        except ValueError:
            pass
    data['devices'][first]['enabled']=True
    (root/'phone.json').write_text(json.dumps(data))
    failed=normalize_result(types.CallToolResult(content=[types.TextContent(type='text',text='Non-ASCII text is not supported on Android. Please fix the issue and try again.')]))
    assert failed.is_error and 'mobile_set_text' in failed.content[0].text
    async with stdio_client(StdioServerParameters(command=sys.executable,args=[sys.argv[2],str(root)])) as (r,w):
        async with ClientSession(r,w) as client:
            await client.initialize()
            tools=(await client.list_tools()).tools
            assert len(tools)==11
            assert all('device' not in t.input_schema['properties'] for t in tools)
            assert all('locale' not in t.input_schema['properties'] for t in tools)
            assert all('resource_id' in t.input_schema['required'] for t in tools if t.name!='mobile_list_devices')
            listed=await client.call_tool('mobile_list_devices',{})
            assert not listed.is_error
            assert len(json.loads(listed.content[0].text))==2
            guard=DeviceLock(lock_path(first))
            guard.acquire()
            try:
                busy=await client.call_tool('mobile_get_screen_size',{'resource_id':first})
                assert busy.is_error and '另一项操作' in busy.content[0].text
                other=await client.call_tool('mobile_get_screen_size',{'resource_id':second})
                assert other.is_error and '离线' in other.content[0].text
            finally:
                guard.release()
            denied=await client.call_tool('mobile_type_keys',{'resource_id':first,'device':'wrong-device','text':'private-test-text','submit':False})
            assert denied.is_error and '不能直接指定' in denied.content[0].text
            data['devices'][first]['enabled']=False
            (root/'phone.json').write_text(json.dumps(data))
            paused=await client.call_tool('mobile_get_screen_size',{'resource_id':first})
            assert paused.is_error and '已暂停' in paused.content[0].text
            assert current_binding(root,second)['enabled']
            data['devices'].pop(first)
            data['selected']=second
            (root/'phone.json').write_text(json.dumps(data))
            changed=await client.call_tool('mobile_get_screen_size',{'resource_id':first})
            assert changed.is_error and '不能自动改用' in changed.content[0].text
            missing=await client.call_tool('mobile_get_screen_size',{})
            assert missing.is_error
    receipts=(root/'runtime/mobile/actions.jsonl').read_text()
    assert 'private-test-text' not in receipts
    entries=[json.loads(line) for line in receipts.splitlines()]
    assert len(entries)==6 and entries[0]['status']=='busy'
    assert all(e['status']=='blocked' for e in entries[1:])
    assert len({e['action_id'] for e in entries})==6
    print('MCP multi-device routing, independent locks, pause, offline and receipt privacy passed')
asyncio.run(main())
''')
    proxy = Path(__file__).resolve().parents[1] / "src/wearing/phone_proxy.py"
    result = subprocess.run([str(runtime.python), str(script), str(tmp_path), str(proxy)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr[-4000:]


async def test_registry_migrates_and_preserves_other_phones(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    write_private_json(tmp_path / 'phone.json', {'serial': 'old', 'enabled': False, 'name': 'Old phone'})
    monkeypatch.setattr(mobile, 'installed', lambda _: {'version': mobile.VERSION})
    monkeypatch.setattr(android, 'devices', lambda _: {'state': 'checked', 'devices': [
        {'serial': 'new', 'model': 'New phone', 'state': 'device', 'android_version': '14'}], 'usb': []})
    await runtime.bind_phone('new')
    old, new = mobile.resource_id('old'), mobile.resource_id('new')
    data = mobile.registry(tmp_path)
    assert data['schema_version'] == 2 and len(data['devices']) == 2
    assert data['devices'][old]['enabled'] is False
    runtime.pause_phone(new)
    runtime.set_phone_enabled(old, True)
    records = mobile.registry(tmp_path)['devices']
    assert records[old]['enabled'] and not records[new]['enabled']
    result = await runtime.phone_status()
    assert not next(r for r in result['resources'] if r['resource_id'] == old)['online']
    assert next(r for r in result['resources'] if r['resource_id'] == new)['online']


def test_registry_corruption_is_not_overwritten(tmp_path):
    path = tmp_path / 'phone.json'
    path.write_text('{bad json')
    with pytest.raises(ValueError, match='原记录已保留'):
        mobile.registry(tmp_path)
    assert path.read_text() == '{bad json'


def test_native_field_guard_requires_fresh_unique_editable_nonpassword():
    from wearing.android_text import focused_field
    xml = '<hierarchy><node class="miui.widget.ClearableEditText" resource-id="android:id/input" package="com.android.settings" focused="true" enabled="true" password="false" text="旧文字" /></hierarchy>'
    assert focused_field(xml, '旧文字')['resource-id'] == 'android:id/input'
    for changed in (xml.replace('focused="true"', 'focused="false"'),
                    xml.replace('password="false"', 'password="true"'),
                    xml.replace('enabled="true"', 'enabled="false"'),
                    xml.replace('resource-id="android:id/input"', 'resource-id=""'),
                    xml.replace('</hierarchy>', xml.removeprefix('<hierarchy>'))):
        with pytest.raises(ValueError):
            focused_field(changed, '旧文字')
    with pytest.raises(ValueError, match='已经变化'):
        focused_field(xml, '之前的文字')


@pytest.mark.parametrize('failure', ['mismatch', 'lost_response', None])
def test_native_write_is_single_attempt_with_readback_and_cleanup(monkeypatch, failure):
    import sys
    from types import SimpleNamespace
    from wearing.android_text import replace_text
    calls = []
    xml = '<hierarchy><node class="android.widget.EditText" resource-id="app:id/input" package="app" focused="true" enabled="true" text="before" /></hierarchy>'
    values = iter(['before', 'wrong' if failure == 'mismatch' else '你好'])
    field = SimpleNamespace(selector={'resourceId': 'app:id/input'}, get_text=lambda **_: next(values))
    class Device:
        _dev = object()
        def dump_hierarchy(self): return xml
        def __call__(self, **_): return field
        def stop_uiautomator(self): calls.append('cleanup')
    def write(*args):
        calls.append('write')
        if failure == 'lost_response': raise ConnectionError('response lost')
        return True
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: Device()))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=write))
    result = replace_text({'serial':'synthetic','expected_text':'before','text':'你好'})
    assert calls == ['write', 'cleanup']
    assert result['ok'] == (failure is None)
    if failure: assert result['unknown']
    else: assert result['input_readback_verified']


def test_native_observation_returns_grounded_coordinates_and_masks_password():
    from wearing.android_text import describe_hierarchy
    xml = '<hierarchy><node class="android.widget.EditText" text="secret" password="true" resource-id="app:id/pw" package="app" bounds="[10,20][110,60]" focused="true" enabled="true"/><node text="外卖" bounds="[30,80][130,120]" clickable="true" enabled="true"/><node text="hidden" bounds="[0,0][0,0]"/></hierarchy>'
    result = describe_hierarchy(xml)
    assert len(result['elements']) == 2
    assert 'secret' not in json.dumps(result)
    assert result['elements'][0]['x'] == 60 and result['elements'][0]['y'] == 40
    assert result['elements'][1]['text'] == '外卖'
    with pytest.raises(ValueError, match='截图'):
        describe_hierarchy('<hierarchy/>')


@pytest.mark.parametrize('mode', ['app', 'system_only', 'timeout'])
def test_observation_is_bounded_single_read_and_reports_incomplete_screen(monkeypatch, mode):
    import sys
    from types import SimpleNamespace
    from wearing.android_text import observe
    calls = []
    monkeypatch.setattr('wearing.android_text.time.sleep', lambda _: None)
    device = SimpleNamespace(_dev=object(), stop_uiautomator=lambda: calls.append('cleanup'))
    def read(dev, port, method, params, timeout, debug):
        calls.append('read')
        assert port == 19008 and method == 'dumpWindowHierarchy' and 0 < timeout <= 8
        if mode == 'timeout':
            raise TimeoutError()
        package = 'com.android.systemui' if mode == 'system_only' else 'app'
        return f'<hierarchy><node text="visible" package="{package}" bounds="[0,0][20,20]"/></hierarchy>'
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: device))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=read))
    result = observe({'serial': 'synthetic'})
    assert calls == (['read'] * (3 if mode == 'system_only' else 1)) + ['cleanup']
    assert result['ok'] == (mode != 'timeout')
    if mode == 'system_only':
        assert result['limited'] and '截图' in result['message']
    elif mode == 'app':
        assert not result['limited']
    else:
        assert '截图' in result['message']


def test_observation_waits_for_empty_transition_without_repeating_actions(monkeypatch):
    import sys
    from types import SimpleNamespace
    from wearing.android_text import observe
    calls = []
    device = SimpleNamespace(_dev=object(), stop_uiautomator=lambda: calls.append('cleanup'))
    screens = iter(['<hierarchy/>', '<hierarchy><node text="已加载" package="app" bounds="[0,0][20,20]"/></hierarchy>'])
    def read(*args): calls.append('read'); return next(screens)
    monkeypatch.setattr('wearing.android_text.time.sleep', lambda _: None)
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: device))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=read))
    result = observe({'serial': 'synthetic'})
    assert result['ok'] and result['observation_attempts'] == 2
    assert calls == ['read', 'read', 'cleanup']


@pytest.mark.parametrize('private', [False, True])
def test_decorated_input_reports_readback_without_claiming_verified_or_retyping(monkeypatch, private):
    import sys
    from types import SimpleNamespace
    from wearing.android_text import replace_text
    before = '<hierarchy><node class="android.widget.EditText" resource-id="app:id/input" package="app" focused="true" enabled="true" text="搜索, " /></hierarchy>'
    after = before.replace('搜索, ', '搜索, 泉州').replace('enabled="true"', f'enabled="true" password="{str(private).lower()}"')
    trees, values = iter([before, after]), iter(['搜索, ', '搜索, 泉州'])
    calls = []
    field = SimpleNamespace(selector={}, get_text=lambda **_: next(values))
    class Device:
        _dev = object()
        def dump_hierarchy(self): return next(trees)
        def __call__(self, **_): return field
        def stop_uiautomator(self): calls.append('cleanup')
    def write(*args): calls.append('write'); return True
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: Device()))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=write))
    result = replace_text({'serial': 'synthetic', 'expected_text': '搜索, ', 'text': '泉州'})
    assert not result['ok'] and not result['input_readback_verified'] and result['unknown']
    assert ('observed_text' in result) is not private
    if not private: assert result['observed_text'] == '搜索, 泉州'
    assert calls == ['write', 'cleanup']
