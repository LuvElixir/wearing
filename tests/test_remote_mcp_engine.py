"""Real pinned Hermes discovery and next-turn schemas, without any model request."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from wearing.cloud.instance import initialize_instance
from wearing.runtime import HermesRuntime


SCRIPT = r'''
import json, os, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.mcp_tool_common import _core
from tools.registry import registry
from model_tools import get_tool_definitions, _dispatch_bridge_tool
from agent.turn_context import _refresh_mcp_tools_between_turns
root=Path(sys.argv[3]);flag=root/'data/remote-devices.json'
def write_flag(enabled):
    flag.write_text(json.dumps({'schema_version':1,'enabled':enabled}));flag.chmod(0o600)
prefix='mcp__wearing_devices__'
def registered():
    return {e.name for e in registry.get_all_entries() if e.name.startswith(prefix)}
def wait_for(expected):
    deadline=time.monotonic()+12
    wanted={prefix+n for n in expected}
    while registered()!=wanted and time.monotonic()<deadline:time.sleep(.1)
    assert registered()==wanted, (registered(),wanted)
    definitions=get_tool_definitions(enabled_toolsets=['wearing_devices'],quiet_mode=True,skip_tool_search_assembly=True)
    assert {t['function']['name'] for t in definitions if t['function']['name'].startswith(prefix)}==wanted
    # Invoke the upstream hook used before a model request on an existing agent
    # snapshot. This is deliberately not a provider/model acceptance claim.
    _refresh_mcp_tools_between_turns(agent)
    if 'tool_search' in agent.valid_tool_names:
        assert {'tool_search','tool_describe','tool_call'} <= agent.valid_tool_names
        result,redirect=_dispatch_bridge_tool('tool_search',{'queries':sorted(wanted) or ['wearing_devices']},
            agent.enabled_toolsets,agent.disabled_toolsets)
        assert redirect is None
        assert set(json.loads(result)['tools'])==wanted
        # The real model bridge resolves freshly added schemas and drops revoked
        # ones even if a conversation still holds its tool_search prefix.
        result,redirect=_dispatch_bridge_tool('tool_describe',{'names':sorted(wanted) or [prefix+'wearing_list_devices']},
            agent.enabled_toolsets,agent.disabled_toolsets)
        assert redirect is None and set(json.loads(result)['tools'])==wanted
    else:
        assert {n for n in agent.valid_tool_names if n.startswith(prefix)}==wanted
def pair(spec, token):
    # The relay SDK belongs to the host interpreter, just like production. Do not
    # inject its ABI-specific dependencies into the managed Hermes environment.
    code="""import json,sys;from pathlib import Path
sys.path.insert(0,sys.argv[1])
from wearing.cloud.relay import instance_relay,PairRequest
from wearing.cloud.device_setup import tools_for
store=instance_relay(Path(sys.argv[2]));spec=json.loads(sys.argv[3])
value=store.pair_code('daily',[spec],tools_for([spec]))
store.pair(PairRequest(code=value['code'],token=sys.argv[4]*64))
"""
    subprocess.run([sys.argv[4],'-c',code,sys.argv[2],str(root),json.dumps(spec),token],check=True,capture_output=True)
agent=SimpleNamespace(tools=[],valid_tool_names=set(),enabled_toolsets=['wearing_devices'],disabled_toolsets=None)
try:
    assert discover_mcp_tools(['wearing_devices'])==[]
    connections=list(_core._servers.values());assert len(connections)==1
    original=connections[0]
    wait_for([])
    write_flag(True)
    wait_for(['wearing_list_devices'])
    pair({'resource_id':'computer_test','kind':'computer','name':'Synthetic desktop',
          'methods':['computer.status','computer.observe']},'a')
    wait_for(['wearing_list_devices','wearing_computer_observe'])
    pair({'resource_id':'phone_test','kind':'android','name':'Synthetic phone',
          'methods':['phone.mobile_press_button']},'b')
    wait_for(['wearing_list_devices','wearing_computer_observe','mobile_press_button'])
    write_flag(False)
    wait_for([])
    flag.unlink();wait_for([])
    write_flag(True)
    wait_for(['wearing_list_devices','wearing_computer_observe','mobile_press_button'])
    assert list(_core._servers.values())==[original], 'Discovery replaced the live MCP connection'
    print('REAL_PINNED_MCP_DYNAMIC_OK',flush=True)
finally:shutdown_mcp_servers(timeout=3)
'''


def test_pinned_hermes_refreshes_catalog_and_next_turn_without_engine_restart(tmp_path):
    project=Path(__file__).resolve().parents[1]
    runtime=HermesRuntime(project/'.wearing')
    if not runtime.python.is_file():pytest.skip('Pinned local engine is not installed')
    root=tmp_path/'instance';initialize_instance(root,'tenant_test','http://127.0.0.1:18865')
    home=tmp_path/'home';home.mkdir()
    config={'mcp_servers':{'wearing_devices':{'command':sys.executable,
        'args':[str(project/'src/wearing/remote_proxy.py'),str(root),'daily'],'timeout':30}}}
    (home/'config.yaml').write_text(yaml.safe_dump(config))
    env=runtime.env();env['HERMES_HOME']=str(home)
    # No inherited provider secrets are necessary for schema discovery.
    for key in list(env):
        if key.endswith(('_API_KEY','_TOKEN')):env.pop(key,None)
    result=subprocess.run([str(runtime.python),'-c',SCRIPT,str(runtime.source),str(project/'src'),str(root),sys.executable],
        env=env,cwd=tmp_path,capture_output=True,text=True,timeout=75)
    assert result.returncode==0, (result.stdout+result.stderr)[-6500:]
    assert 'REAL_PINNED_MCP_DYNAMIC_OK' in result.stdout
