"""Final-dispatch guard for a durable confirmation's read-only recovery run.

Installed by the managed runner, after import of the pinned Hermes executor.
Neither a system prompt nor model-provided metadata can disable this guard.
"""
import functools
import json
import os
from pathlib import Path

from .durable_confirmations import DurableConfirmations, PREFIX, LIVE, ConfirmationError
from .store import Store

READ_ONLY = frozenset(PREFIX + name for name in (
    "life_records", "goal_list", "schedule_list", "artifact_list", "artifact_read",
    "artifact_design_guide", "cloud_connections", "cloud_feishu_files",
    "cloud_feishu_document", "cloud_feishu_calendars", "cloud_feishu_events",
)) | frozenset({"web_search", "web_extract", "mcp__wearing_devices__wearing_list_devices",
               "mcp__wearing_phone__mobile_list_devices"}) | frozenset(
    "mcp__" + server + "__" + name
    for server in ("wearing_devices", "wearing_phone")
    for name in ("mobile_list_apps", "mobile_get_screen_size", "mobile_list_elements_on_screen", "mobile_take_screenshot")
)
CONFIRM = PREFIX + "request_confirmation"


def read_only(tool, args):
    if tool in READ_ONLY:
        return True
    return (tool == "mcp__wearing_devices__wearing_computer_observe"
            and args.get("action") in {"status", "list_apps", "list_windows", "capture"}
            and not set(args) - {"resource_id", "action", "app", "window_id", "pid"})


def succeeded(result):
    """Only record a read whose returned tool envelope does not report failure."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return False
    if not isinstance(result, dict) or result.get("error") or result.get("isError"):
        return False
    for part in result.get("content", []):
        if isinstance(part, dict) and part.get("type") == "text":
            try:
                payload = json.loads(part.get("text", ""))
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and (payload.get("error") or payload.get("isError")):
                return False
    return True


class ConfirmationGuard:
    def __init__(self, store, identity):
        store.identity(identity)
        self.store, self.identity = store, identity
        self.book = DurableConfirmations(store)

    def task_for_run(self, run_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM tasks WHERE identity_id=? AND run_id=?", (self.identity, run_id)).fetchall()
            if len(rows) == 1:
                return dict(rows[0])
            # /runs returns before App records run_id. The unique reserved start
            # is already bound to the guard table, so there is no unguarded gap.
            pending = db.execute("""SELECT * FROM tasks WHERE identity_id=? AND status='starting' AND run_id IS NULL""", (self.identity,)).fetchall()
            if len(pending) == 1:
                return dict(pending[0])
        raise ConfirmationError("当前工具调用无法绑定到唯一运行，未执行。")

    def execute(self, task, tool, args, execute):
        with self.store.connection() as db:
            recovery = db.execute("SELECT * FROM confirmation_recovery_tasks WHERE task_id=?", (task["id"],)).fetchone()
            related = db.execute("SELECT 1 FROM durable_confirmations WHERE task_id=?", (task["id"],)).fetchone()
            unresolved = db.execute("""SELECT 1 FROM durable_confirmations WHERE task_id=?
                AND state IN ('pending','sending','unknown','needs_recheck','denied')""", (task["id"],)).fetchone()
        if (recovery or related) and (task["status"] not in LIVE or task["status"] == "stopping"):
            raise ConfirmationError("该运行已结束，旧执行上下文不能继续操作。")
        if not recovery and not unresolved:
            return execute(args)
        if read_only(tool, args):
            snapshot = self.book.read_snapshot(task, tool, args)
            result = execute(args)
            if succeeded(result):
                self.book.record_read(task, tool, snapshot)
            return result
        if tool == CONFIRM:
            # The MCP book validates observations, revisions and one new card.
            return execute(args)
        if recovery and self.book.consume(task, tool, args):
            try:
                result = execute(args)
            except BaseException:
                self.book.execution_result(task["id"], False)
                raise
            self.book.execution_result(task["id"], succeeded(result))
            return result
        raise ConfirmationError("本轮只允许读取当前状态。旧卡未授权操作；请基于实际读取的最新版本请求新的单次确认。不得换工具或委派绕过。")


def install_confirmation_guard():
    root = os.environ.get("PAJIO_CONFIRMATION_DATA_DIR")
    identity = os.environ.get("PAJIO_CONFIRMATION_IDENTITY")
    if not root and not identity:
        return False  # Unmanaged upstream/isolated tests have no product ledger.
    path = Path(root or "") / "wearing.sqlite3"
    if not root or not identity or not path.is_file():
        raise RuntimeError("Pajio confirmation guard has no trusted task store")
    from agent import tool_executor
    from tools.approval_context import get_current_session_key
    current = tool_executor._dispatch_authorized_once
    if getattr(current, "_pajio_confirmation_guard", False):
        return True
    guard = ConfirmationGuard(Store(path), identity)

    @functools.wraps(current)
    def dispatch(agent, state, ref, *, execute, **kwargs):
        def checked(actual_args):
            try:
                task = guard.task_for_run(get_current_session_key())
                return guard.execute(task, ref.name, actual_args, execute)
            except ConfirmationError as error:
                state.blocked = True
                return json.dumps({"error": "confirmation_recheck_read_only", "message": str(error)}, ensure_ascii=False)
        # Hermes performs all parameter rewrites first, then calls checked with
        # the final arguments. This applies to sequential and concurrent tools.
        return current(agent, state, ref, execute=checked, **kwargs)

    dispatch._pajio_confirmation_guard = True
    tool_executor._dispatch_authorized_once = dispatch
    return True
