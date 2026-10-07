import json
from pathlib import Path
import subprocess

import httpx
import pytest
import yaml

from wearing.app import create_app
from wearing.config import Settings
from wearing.filesystem import TOOLS, configuration
from wearing.profile import prepare_profile
from wearing.runtime import HermesRuntime
from wearing.workspace import list_files, workspace_file, WorkspaceError


def test_download_and_listing_do_not_follow_symlinks_or_parent_paths(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("outside canary")
    (root / "safe.md").write_text("hello")
    (root / "link").symlink_to(outside)
    (root / "directory-link").symlink_to(tmp_path, target_is_directory=True)
    assert [f["path"] for f in list_files(root)["files"]] == ["safe.md"]
    for name in ("../private.txt", str(outside), "link", "directory-link/private.txt", "..\\private.txt"):
        with pytest.raises(WorkspaceError):
            workspace_file(root, name)
    assert workspace_file(root, "safe.md").read_text() == "hello"


async def test_download_is_attachment_and_active_turn_blocks_configuration(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path))
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "hello.html").write_text("<script>alert(1)</script>")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/model", json={})).status_code == 403
        token = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Wearing-Token"] = token
        file = await client.get("/api/workspace/file", params={"path": "hello.html"})
        assert file.headers["content-type"] == "application/octet-stream"
        assert "attachment" in file.headers["content-disposition"]
        assert (await client.get("/api/workspace/file", params={"path": "../connection.json"})).status_code == 404
        too_long = await client.post("/api/model", json={"provider": "deepseek", "model": "x", "key": "test-secret" * 500})
        assert too_long.status_code == 422
        assert "test-secret" not in too_long.text
        task = app.state.store.create("working", "computer")
        app.state.store.update(task["id"], status="running")
        for path, body in (("/api/model", {"provider": "deepseek", "model": "x", "key": "test-secret"}), ("/api/workspace/enable", {})):
            result = await client.post(path, json=body)
            assert result.status_code == 409
            assert "test-secret" not in result.text
    await app.state.service.hermes.close()


def test_profile_restricts_mcp_to_file_connector(tmp_path):
    home, source = tmp_path / "home", tmp_path / "source"
    home.mkdir()
    (home / "config.yaml").write_text("mcp_servers:\n  unrelated:\n    command: never-start\n")
    prepare_profile(home, source)
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["platform_toolsets"]["api_server"] == ["memory", "session_search", "web", "todo", "skills", "vision"]
    files = {"command": "test-node", "args": ["test-server", "workspace"], "tools": {"include": list(TOOLS)}}
    prepare_profile(home, source, files)
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["platform_toolsets"] == {"api_server": ["memory", "session_search", "web", "todo", "skills", "vision", "wearing_files"], "cli": ["no_mcp"]}
    assert config["mcp_servers"]["unrelated"]["command"] == "never-start"
    assert config["mcp_servers"]["wearing_files"] == files


def test_real_filesystem_mcp_can_write_read_but_not_escape(tmp_path):
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    root = tmp_path / "files"
    root.mkdir()
    files = configuration(runtime.root, root)
    if not files:
        pytest.skip("Enable the pinned filesystem connector to run its integration contract")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-canary")
    (root / "outside-link").symlink_to(outside)
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("mcp_servers:\n  unrelated:\n    command: never-start\n")
    prepare_profile(home, runtime.source, files)
    # This exercises Hermes' real schema filtering and MCP dispatch, without an LLM.
    script = '''
import json,sys
from pathlib import Path
from tools.mcp_tool_discovery import discover_mcp_tools
from tools.mcp_tool_lifecycle import shutdown_mcp_servers
from tools.registry import registry
from hermes_cli.tools_config import _get_platform_tools
from hermes_cli.config import load_config
root=Path(sys.argv[1]); outside=Path(sys.argv[2])
expected=set(json.loads(sys.argv[3]))
try:
 names=discover_mcp_tools(['wearing_files'])
 assert set(names)=={'mcp__wearing_files__'+n for n in expected}, names
 assert _get_platform_tools(load_config(),'api_server') == {'memory','session_search','web','todo','skills','vision','wearing_files'}
 def call(name,args): return registry.dispatch('mcp__wearing_files__'+name,args)
 allowed=call('list_allowed_directories',{}); assert str(root) in allowed
 call('write_file',{'path':str(root/'hello.txt'),'content':'wearing-canary'})
 assert (root/'hello.txt').read_text()=='wearing-canary'
 assert 'wearing-canary' in call('read_text_file',{'path':str(root/'hello.txt')})
 for path in (str(outside),str(root/'../outside.txt'),str(root/'outside-link')):
  result=call('read_text_file',{'path':path}); assert 'outside-canary' not in result, result
  assert 'denied' in result.lower() or 'error' in result.lower(), result
 result=call('write_file',{'path':str(outside),'content':'changed'})
 assert outside.read_text()=='outside-canary', result
 assert 'Unknown tool' in call('move_file',{'source':str(root/'hello.txt'),'destination':str(outside)})
 print('PASS filesystem scope, actual I/O, symlink and traversal rejection, exact six tools')
finally:
 shutdown_mcp_servers(timeout=3.0)
'''
    env = runtime.env()
    env["HERMES_HOME"] = str(home)
    result = subprocess.run([str(runtime.python), "-c", script, str(root), str(outside), json.dumps(TOOLS)],
                            cwd=runtime.source, env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS filesystem" in result.stdout
