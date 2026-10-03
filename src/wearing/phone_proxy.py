"""Wearing resource routing over Mobile MCP and pinned UiAutomator2.

Every device action requires an enrolled resource_id. stdout is MCP-only.
"""
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

try:
    from .mobile import TOOLS, registry, read_capabilities, u2_python, u2_installed
except ImportError:
    from mobile import TOOLS, registry, read_capabilities, u2_python, u2_installed


class DeviceBusy(Exception):
    pass


class DeviceLock:
    """OS advisory lock, also released if the connector process exits."""
    def __init__(self, path):
        self.path, self.stream = path, None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        self.stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.stream.write(b"\0")
                self.stream.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.release()
            raise DeviceBusy() from error

    def release(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def lock_path(rid):
    # Shared across Wearing profiles: two local instances cannot drive one phone.
    return Path.home() / ".wearing/phone-locks" / (rid + ".lock")


def current_binding(data_dir, rid):
    records = registry(data_dir)["devices"]
    if not isinstance(rid, str) or rid not in records:
        raise ValueError("请从 mobile_list_devices 选择已接入的 resource_id；不能自动改用其他手机。")
    value = records[rid]
    if not value.get("enabled"):
        raise ValueError("这部手机操作已暂停。请用户在 Wearing 的连接设置中恢复，不能自行绕过。")
    return value


def prepare_arguments(name, arguments, serial):
    if name not in TOOLS:
        raise ValueError("Wearing 未开放这项手机操作。")
    args = dict(arguments or {})
    if "device" in args:
        raise ValueError("请使用已接入的 resource_id，不能直接指定设备编号。")
    if "locale" in args:
        raise ValueError("启动应用不包含更改应用语言，请使用当前语言。")
    args.pop("resource_id", None)
    args["device"] = serial
    return args


def receipt(data_dir, name, status, duration, **extra):
    # No typed text, screenshots, screen contents or account data in this journal.
    path = data_dir / "runtime/mobile/actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    entry = {"at": datetime.now(timezone.utc).isoformat(), "tool": name, "status": status,
             "duration_ms": round(duration * 1000), **extra}
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record_capability(data_dir, rid, capability):
    path = data_dir / "runtime/mobile" / rid / "capabilities.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = read_capabilities(data_dir, rid)
    data[capability] = {"verified_at": datetime.now(timezone.utc).isoformat()}
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream)
    temp.replace(path)


def normalize_result(result):
    if any(isinstance(c, types.TextContent) and c.text.endswith("Please fix the issue and try again.") for c in result.content):
        result.is_error = True
    for content in result.content:
        if isinstance(content, types.TextContent) and content.text.startswith("Non-ASCII text is not supported on Android"):
            result.is_error = True
            content.text = "此基础输入通道没有输入中文。请读取当前输入框，使用 mobile_set_text 填写中文并核对结果。"
    return result


def scoped_schema(tool):
    schema = json.loads(json.dumps(tool.input_schema))
    properties = schema.setdefault("properties", {})
    properties.pop("device", None)
    properties.pop("locale", None)
    properties["resource_id"] = {"type": "string", "description": "mobile_list_devices 返回的已接入手机 resource_id"}
    schema["required"] = [name for name in schema.get("required", []) if name not in ("device", "locale")] + ["resource_id"]
    description = (tool.description or "").replace("list_apps_on_device", "mobile_list_apps")
    if tool.name == "mobile_type_keys":
        description += " 英文和数字输入。中文请读取输入框后使用 mobile_set_text；不要用拼音代替用户指定文字。"
    return types.Tool(name=tool.name, description="操作指定的 Wearing 手机资源。" + description,
                      input_schema=schema, annotations=tool.annotations)


def extra_schemas():
    return [types.Tool(name="mobile_list_devices", description="列出已接入 Wearing 的手机、在线与暂停状态。先选明确的 resource_id；用户没有指明且存在多台可用手机时，先澄清。离线或暂停不可改用另一台。",
                      input_schema={"type": "object", "properties": {}, "additionalProperties": False}),
            types.Tool(name="mobile_set_text", description="替换当前聚焦的 Android 原生输入框全文，支持中文。先读取当前界面，将刚观察的原文字传入 expected_text；本工具核对旧值、单次填写并读回校验，不点击提交。密码框、无稳定标识的输入框不支持。失败或未知时重新观察，不盲目重试。",
                       input_schema={"type": "object", "properties": {
                           "resource_id": {"type": "string"}, "text": {"type": "string", "maxLength": 12000},
                           "expected_text": {"type": "string", "maxLength": 12000}},
                           "required": ["resource_id", "text", "expected_text"], "additionalProperties": False})]


async def run_child(command, env, payload=None, timeout=15):
    process = await asyncio.create_subprocess_exec(*command, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout)
        if process.returncode:
            raise RuntimeError("connector process failed")
        return output
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 12)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


async def device_states(data_dir, env):
    adb = data_dir / "runtime/android/platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    output = (await run_child([str(adb), "devices"], env)).decode("utf-8", "replace")
    return {parts[0]: parts[1] for line in output.splitlines() if len(parts := line.split()) == 2 and parts[1] in ("device", "offline", "unauthorized")}


async def native_input(data_dir, config, args, env):
    if set(args) != {"resource_id", "text", "expected_text"} or not all(isinstance(args[k], str) and len(args[k]) <= 12000 for k in ("text", "expected_text")):
        raise ValueError("填写需要 resource_id、text 和刚观察到的 expected_text。")
    if not u2_installed(data_dir / "runtime"):
        raise ValueError("请在连接设置中准备中文输入组件，再填写中文。")
    payload = json.dumps({"serial": config["serial"], "text": args["text"], "expected_text": args["expected_text"]}).encode()
    output = await run_child([str(u2_python(data_dir / "runtime")), str(Path(__file__).with_name("android_text.py"))], env, payload, timeout=55)
    result = json.loads(output)
    if result.get("input_readback_verified"):
        record_capability(data_dir, args["resource_id"], "native_text_readback")
    return types.CallToolResult(is_error=not result.get("ok"), content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])


async def read_screen(client, args, data_dir, config, env):
    """Prefer one bounded native read; do not stack competing UI dump sessions."""
    if u2_installed(data_dir / "runtime"):
        current_binding(data_dir, config["resource_id"])
        payload = json.dumps({"serial": config["serial"], "operation": "observe"}).encode()
        output = await run_child([str(u2_python(data_dir / "runtime")), str(Path(__file__).with_name("android_text.py"))], env, payload, timeout=15)
        observed = json.loads(output)
        return types.CallToolResult(is_error=not observed.get("ok"), content=[types.TextContent(type="text", text=json.dumps(observed, ensure_ascii=False))])
    # The legacy driver's own retry loop can outlive a cancelled MCP request.
    # Never start UiAutomator2 after timing that request out: both would own
    # Android's UI automation channel at once. Ask for a screenshot instead.
    try:
        return normalize_result(await asyncio.wait_for(client.call_tool("mobile_list_elements_on_screen", args), timeout=20))
    except asyncio.TimeoutError:
        return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text="界面读取超时，请使用截图观察。")])


async def serve(data_dir):
    installed = json.loads((data_dir / "runtime/mobile/installed.json").read_text())
    registry(data_dir)  # Validate before starting any driver.
    adb_dir = data_dir / "runtime/android/platform-tools"
    env = {k: v for k, v in os.environ.items() if k in ("HOME", "USERPROFILE", "SystemRoot", "TEMP", "TMP", "TMPDIR", "PATH", "LANG")}
    env.update(MOBILEMCP_DISABLE_TELEMETRY="1", MOBILEMCP_LEGACY_ROBOT="1", ADBUTILS_ADB_PATH=str(adb_dir / ("adb.exe" if os.name == "nt" else "adb")),
               PATH=str(adb_dir) + os.pathsep + env.get("PATH", ""))
    async with AsyncExitStack() as stack:
        error_log = stack.enter_context(open(os.devnull, "w"))
        incoming, outgoing = await stack.enter_async_context(stdio_client(StdioServerParameters(
            command=installed["node"], args=[str(data_dir / "runtime/mobile/node_modules/@mobilenext/mobile-mcp/lib/index.js")], env=env), errlog=error_log))
        client = await stack.enter_async_context(ClientSession(incoming, outgoing))
        await client.initialize()
        schemas = (await client.list_tools()).tools
        allowed = {tool.name: scoped_schema(tool) for tool in schemas if tool.name in TOOLS}
        if set(allowed) != set(TOOLS):
            raise ValueError("Mobile MCP 工具与固定版本预期不一致。")
        allowed.update({tool.name: tool for tool in extra_schemas()})

        async def list_tools(context, params):
            return types.ListToolsResult(tools=list(allowed.values()))

        async def call_tool(context, params):
            name, arguments = params.name, params.arguments or {}
            rid = arguments.get("resource_id")
            ids = {"action_id": uuid.uuid4().hex, "resource_id": None}
            started, guard = time.monotonic(), None
            try:
                if name not in allowed:
                    raise ValueError("Wearing 未开放这项手机操作。")
                if name == "mobile_list_devices":
                    states = await device_states(data_dir, env)
                    records = registry(data_dir)["devices"]
                    value = [{"resource_id": key, "name": item.get("name", "Android"), "label": item["serial"][-4:],
                              "platform": item.get("platform", "android"), "android_version": item.get("android_version"),
                              "enabled": item["enabled"], "connection_state": states.get(item["serial"], "disconnected"),
                              "native_input_ready": u2_installed(data_dir / "runtime"), "capabilities": read_capabilities(data_dir, key)} for key, item in records.items()]
                    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(value, ensure_ascii=False))])
                config = current_binding(data_dir, rid)
                ids["resource_id"] = rid
                guard = DeviceLock(lock_path(rid))
                guard.acquire()
                config = current_binding(data_dir, rid)  # Recheck pause after acquiring.
                args = None if name == "mobile_set_text" else prepare_arguments(name, arguments, config["serial"])
                states = await device_states(data_dir, env)
                if states.get(config["serial"]) != "device":
                    raise ValueError("指定手机离线或未授权，尚未执行；请重新连接这部手机，不要换用其他设备。")
                config = current_binding(data_dir, rid)  # Discovery can take time.
                receipt(data_dir, name, "started", 0, **ids)
                if name == "mobile_set_text":
                    result = await native_input(data_dir, config, arguments, env)
                elif name == "mobile_list_elements_on_screen":
                    result = await read_screen(client, args, data_dir, config, env)
                else:
                    result = normalize_result(await asyncio.wait_for(client.call_tool(name, args), timeout=40))
                receipt(data_dir, name, "tool_error" if result.is_error else "returned_unverified", time.monotonic() - started, **ids)
                return result
            except asyncio.CancelledError:
                receipt(data_dir, name, "unknown", time.monotonic() - started, **ids)
                raise
            except DeviceBusy:
                receipt(data_dir, name, "busy", time.monotonic() - started, **ids)
                return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text="这部手机正由另一项操作使用，请稍后重试。")])
            except ValueError as error:
                receipt(data_dir, name, "blocked", time.monotonic() - started, **ids)
                return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=str(error))])
            except Exception:
                receipt(data_dir, name, "unknown", time.monotonic() - started, **ids)
                return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text="手机操作未得到完整结果，请先重新观察屏幕。不要自动重复点击或输入。")])
            finally:
                if guard:
                    guard.release()

        server = Server("wearing-phone", on_list_tools=list_tools, on_call_tool=call_tool)
        read, write = await stack.enter_async_context(stdio_server())
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(serve(Path(sys.argv[1]).resolve()))
