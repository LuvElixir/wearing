"""Wearing host for the pinned Hermes API adapter.

Executed by Hermes' managed interpreter. The agent loop, model resolution,
session persistence, run idempotency and approval logic remain upstream-owned.
No GatewayRunner, platform bots, cron ticker or kanban workers are started.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import sys


ALLOWED_ROUTES = frozenset({
    ("GET", "/health"), ("GET", "/v1/capabilities"),
    ("POST", "/v1/runs"), ("GET", "/v1/runs/{run_id}"),
    ("GET", "/v1/runs/{run_id}/events"),
    ("POST", "/v1/runs/{run_id}/approval"),
    ("POST", "/v1/runs/{run_id}/steer"),
    ("POST", "/v1/runs/{run_id}/stop"),
    ("GET", "/v1/wearing/memory"),
})


def adapter_class():
    from aiohttp import web
    from gateway.platforms.api_server import APIServerAdapter
    try:
        from .research import receipt_items
        from .app_research import APP_TOOLS, app_receipt_items
    except ImportError:  # Script entry point in the managed interpreter.
        from research import receipt_items
        from app_research import APP_TOOLS, app_receipt_items

    class WearingAdapter(APIServerAdapter):
        draining = False
        file_tools = []
        phone_tools = []
        remote_tools = []
        life_tools = []
        profile_version = 0
        computer_enabled = False
        memory_tools = []
        web_tools = []
        planning_tools = []
        skill_tools = []
        media_tools = []
        research_failed_runs = None

        def _make_run_event_callback(self, run_id, loop):
            upstream = super()._make_run_event_callback(run_id, loop)
            def callback(event_type, tool_name=None, preview=None, args=None, **kwargs):
                upstream(event_type, tool_name, preview, args, **kwargs)
                if tool_name in {"web_search", "web_extract"} or tool_name in APP_TOOLS:
                    try:
                        from gateway.platforms.api_server import redact_sensitive_text
                        clean_args = json.loads(redact_sensitive_text(json.dumps(args or {}, ensure_ascii=False), force=True))
                        result = kwargs.get("result")
                        if isinstance(result, dict):
                            result = redact_sensitive_text(json.dumps(result, ensure_ascii=False), force=True)
                        elif isinstance(result, str):
                            result = redact_sensitive_text(result, force=True)
                        items = (app_receipt_items(tool_name, event_type, result, kwargs.get("is_error", False))
                                 if tool_name in APP_TOOLS else receipt_items(tool_name, event_type, clean_args, result, kwargs.get("is_error", False)))
                        self.research.record(run_id, items)
                    except Exception:
                        self.research_failed_runs.add(run_id)
                        logging.getLogger(__name__).warning("Research receipt could not be saved")
            return callback

        async def _handle_get_run(self, request):
            # The upstream owner/auth checks execute before any receipt is read.
            response = await super()._handle_get_run(request)
            if response.status == 200:
                data = json.loads(response.body)
                run_id = request.match_info["run_id"]
                try:
                    data["research"] = await asyncio.to_thread(self.research.snapshot, run_id)
                    if run_id in self.research_failed_runs:
                        data["research"]["unavailable"] = True
                except (OSError, ValueError, sqlite3.Error):
                    data["research"] = {"items": [], "unavailable": True}
                return web.json_response(data)
            return response

        def _http_route_table(self):
            routes = [r for r in super()._http_route_table() if (r[0], r[1]) in ALLOWED_ROUTES]
            return routes + [("GET", "/v1/wearing/memory", self._handle_memory)]

        async def _handle_memory(self, request):
            denied = self._check_auth(request)
            if denied is not None:
                return denied
            try:
                data = await asyncio.to_thread(memory_snapshot)
            except (OSError, ValueError):
                return web.json_response({"error": "无法读取本身份的记忆；原文件未改动。"}, status=503)
            return web.json_response(data)

        def _make_profile_prefix_middleware(self):
            parent = super()._make_profile_prefix_middleware()

            @web.middleware
            async def one_profile(request, handler):
                if request.path.startswith("/p/"):
                    raise web.HTTPNotFound()
                return await parent(request, handler)
            return one_profile

        def _wire_plugin_handlers(self, app):
            # Plugins cannot silently expand this product's HTTP surface.
            return None

        def _gateway_is_draining(self):
            return self.draining

        async def _handle_health(self, request):
            return web.json_response({"status": "ok", "platform": "wearing", "mode": "wearing-personal"})

        async def _handle_capabilities(self, request):
            response = await super()._handle_capabilities(request)
            if response.status != 200:
                return response
            data = json.loads(response.body)
            # Keep the upstream protocol identifier for existing client compatibility.
            data.update(platform="wearing", model="wearing")
            allowed_features = {"run_submission", "runs_idempotency", "run_status", "run_events_sse", "run_stop", "run_steer",
                                "run_approval_response", "tool_progress_events", "approval_events", "reasoning_streaming",
                                "session_continuity_header", "session_key_header"}
            data["features"] = {k: v if k in allowed_features else False for k, v in data["features"].items()}
            data["endpoints"] = {k: v for k, v in data["endpoints"].items() if (v["method"], v["path"]) in ALLOWED_ROUTES}
            data["runtime"] = {"mode": "wearing-personal", "tool_execution": "server", "split_runtime": False}
            data["wearing"] = {"profile_version": self.profile_version, "identity": "Wearing", "scheduler": False, "messaging": False}
            data["wearing"]["memory_tools"] = self.memory_tools
            data["endpoints"]["wearing_memory"] = {"method": "GET", "path": "/v1/wearing/memory"}
            data["wearing"]["computer_tools"] = ["computer_use"] if self.computer_enabled else []
            data["wearing"]["file_tools"] = self.file_tools
            data["wearing"]["phone_tools"] = self.phone_tools
            data["wearing"]["remote_device_tools"] = self.remote_tools
            data["wearing"]["life_tools"] = self.life_tools
            data["wearing"]["web_tools"] = self.web_tools
            data["wearing"]["planning_tools"] = self.planning_tools
            data["wearing"]["skill_tools"] = self.skill_tools
            data["wearing"]["media_tools"] = self.media_tools
            data["wearing"]["research_receipts"] = True
            data["wearing"]["app_observation_receipts"] = True
            return web.json_response(data)

    return WearingAdapter


def memory_snapshot():
    """Read the same upstream store the agent loads; no second memory writer."""
    from datetime import datetime, timezone
    from tools.memory_tool import load_on_disk_store, get_memory_dir
    for name in ("USER.md", "MEMORY.md"):
        path = get_memory_dir() / name
        if path.exists():
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError("Unsafe or oversized memory file")
            path.read_text(encoding="utf-8")
    store = load_on_disk_store()
    return {"available": True, "observed_at": datetime.now(timezone.utc).isoformat(),
            "targets": {target: {"enabled": store.target_enabled(target),
                                 "entries": store._entries_for(target),
                                 "used_chars": store._char_count(target),
                                 "limit_chars": store._char_limit(target)} for target in ("user", "memory")}}


async def serve():
    from gateway.config import PlatformConfig
    adapter = adapter_class()(PlatformConfig(enabled=True, extra={
        "host": "127.0.0.1", "port": int(os.environ["API_SERVER_PORT"]),
        "key": os.environ["API_SERVER_KEY"], "model_name": "wearing", "cors_origins": "",
    }))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops use the synchronous signal bridge.
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        from hermes_cli.config import load_config
        config = load_config()
        manifest_path = Path(os.environ["HERMES_HOME"]) / "wearing-profile.json"
        if manifest_path.exists():
            adapter.profile_version = json.loads(manifest_path.read_text())["version"]
        from tools.memory_tool import get_builtin_memory_store_flags
        toolsets = config.get("platform_toolsets", {}).get("api_server", [])
        from model_tools import get_tool_definitions
        native = [name for name in ("todo", "skills", "vision") if name in toolsets]
        available = {item["function"]["name"] for item in get_tool_definitions(
            enabled_toolsets=native, quiet_mode=True, skip_tool_search_assembly=True)} if native else set()
        adapter.planning_tools = sorted(available & {"todo_list"})
        adapter.skill_tools = sorted(available & {"skills_list", "skill_view", "skill_manage"})
        adapter.media_tools = sorted(available & {"vision_analyze"})
        try:
            from .research import ResearchBook
        except ImportError:
            from research import ResearchBook
        adapter.research = ResearchBook(Path(os.environ["HERMES_HOME"]))
        adapter.research_failed_runs = set()
        if "web" in toolsets:
            from tools.web_tools import check_web_api_key
            adapter.web_tools = ["web_search", "web_extract"] if check_web_api_key() else []
        adapter.memory_tools = (["memory"] if "memory" in toolsets and any(get_builtin_memory_store_flags(config)) else []) + (["session_search"] if "session_search" in toolsets else [])
        adapter.computer_enabled = "computer_use" in config.get("platform_toolsets", {}).get("api_server", [])
        if "wearing_files" in config.get("platform_toolsets", {}).get("api_server", []):
            from tools.mcp_tool_discovery import discover_mcp_tools
            discovered = await asyncio.to_thread(discover_mcp_tools, ["wearing_files"])
            adapter.file_tools = [name for name in discovered if name.startswith("mcp__wearing_files__")]
            if len(adapter.file_tools) != 6:
                raise RuntimeError("Wearing file connector did not expose the expected tools")
        if "wearing_phone" in config.get("platform_toolsets", {}).get("api_server", []):
            from tools.mcp_tool_discovery import discover_mcp_tools
            discovered = await asyncio.to_thread(discover_mcp_tools, ["wearing_phone"])
            adapter.phone_tools = [name for name in discovered if name.startswith("mcp__wearing_phone__")]
            if len(adapter.phone_tools) != 11:
                raise RuntimeError("Wearing phone connector did not expose the expected tools")
        if "wearing_devices" in toolsets:
            from tools.mcp_tool_discovery import discover_mcp_tools
            discovered = await asyncio.to_thread(discover_mcp_tools, ["wearing_devices"])
            adapter.remote_tools = [name for name in discovered if name.startswith("mcp__wearing_devices__")]
            if not any(name.endswith("__wearing_list_devices") for name in adapter.remote_tools):
                raise RuntimeError("Wearing remote connector did not expose its inventory tool")
        if "wearing_life" in toolsets:
            from tools.mcp_tool_discovery import discover_mcp_tools
            discovered = await asyncio.to_thread(discover_mcp_tools, ["wearing_life"])
            adapter.life_tools = [name for name in discovered if name.startswith("mcp__wearing_life__")]
            if {name.split("__")[-1] for name in adapter.life_tools} != {"request_confirmation", "life_records", "life_create", "life_change", "goal_list", "goal_create", "goal_change", "schedule_list", "schedule_create", "schedule_change", "artifact_list", "artifact_read", "artifact_publish", "artifact_design_guide"}:
                raise RuntimeError("Wearing life connector did not expose its expected tools")
        if not await adapter.connect():
            raise RuntimeError("Wearing engine could not bind its local API")
        print("WEARING_ENGINE_READY", flush=True)
        await stop.wait()
    finally:
        adapter.draining = True
        adapter.mark_shutdown_requested()
        adapter.interrupt_active_runs("Wearing is shutting down")
        await adapter.cancel_background_tasks()
        await adapter.disconnect()
        from tools.mcp_tool_lifecycle import shutdown_mcp_servers
        await asyncio.to_thread(shutdown_mcp_servers, timeout=3.0)


def main():
    source = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(source))
    from dotenv import load_dotenv
    if os.environ.get("WEARING_MODEL_ENV"):
        # Model credentials are shared infrastructure, not identity accounts.
        # Only provider key variables are imported from the shared file.
        from dotenv import dotenv_values
        shared = dotenv_values(os.environ["WEARING_MODEL_ENV"])
        for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "MINIMAX_API_KEY"):
            if shared.get(name):
                os.environ[name] = shared[name]
    load_dotenv(Path(os.environ["HERMES_HOME"]) / ".env", override=True)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
