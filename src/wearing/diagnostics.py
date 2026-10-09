"""Allowlisted support snapshots. No prompts, log text, paths or credentials.

Task record updates include ordinary polling. Only explicit state events are used
to describe time without a state transition; neither is an engine heartbeat.
"""
from __future__ import annotations
import asyncio
import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

TASK_STATES = frozenset({"draft", "queued", "starting", "running", "waiting_for_approval", "stopping", "connection_lost", "ambiguous", "failed", "stopped", "completed_unverified", "verified", "closed"})
PHASES = frozenset({"idle", "downloading", "installing", "ready", "running", "failed", "stopped"})
EVENTS = TASK_STATES | {"created", "accepted", "stop_unconfirmed", "approval_answered"}
ERRORS = {"connection_lost": "engine_connection_lost", "ambiguous": "run_state_unknown", "failed": "run_failed", "stop_unconfirmed": "stop_unconfirmed"}
PROBE_STATES = frozenset({"reachable", "unavailable", "not_configured", "not_observed", "timeout"})
SAFE_ID = re.compile(r"^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|run_[a-f0-9]{32})$")
LONG_PHASE_SECONDS = 15 * 60


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            return None
        return date.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def reference(value):
    """Known generated UUIDs remain useful; arbitrary upstream IDs are hashed."""
    if not isinstance(value, str) or not value:
        return None
    return value if SAFE_ID.fullmatch(value) else "ref_" + hashlib.sha256(value.encode()).hexdigest()[:16]


def flag(value):
    return value if isinstance(value, bool) else None


def runtime_summary(value):
    data = value if isinstance(value, dict) else {}
    result = {"phase": data.get("phase") if data.get("phase") in PHASES else "unknown", "running": flag(data.get("running")),
              "installed": flag(data.get("installed")), "error_present": bool(data.get("error")), "connectors": {}}
    for name in ("files", "phone", "computer"):
        item = data.get(name) if isinstance(data.get(name), dict) else {}
        result["connectors"][name] = {"phase": item.get("phase") if item.get("phase") in PHASES else "unknown", "active": flag(item.get("active")), "error_present": bool(item.get("error"))}
    return result


def device_summary(value):
    if not isinstance(value, list):
        return {"state": "not_observed", "items": [], "truncated": False}
    rows = []
    for item in value[:30]:
        if not isinstance(item, dict):
            continue
        rows.append({"kind": item.get("kind") if item.get("kind") in {"computer", "phone", "browser", "desktop", "android", "ios"} else "other",
                     **{key: flag(item.get(key)) for key in ("connected", "online", "paused", "control_pending", "needs_review")},
                     "last_seen_at": stamp(item.get("last_seen_at"))})
    return {"state": "observed", "items": rows, "truncated": len(value) > 30}


class Diagnostics:
    def __init__(self, store, runtime_for, *, probe_for=None, devices_for=None, clock=time.time, probe_timeout=5, require_owner=False):
        self.store, self.runtime_for = store, runtime_for
        self.probe_for, self.devices_for, self.clock, self.probe_timeout = probe_for, devices_for, clock, probe_timeout
        self.require_owner = require_owner
        # Supports bounded recent-task lookups, without reading event messages.
        with store.connection() as db:
            db.execute("CREATE INDEX IF NOT EXISTS diagnostic_events_task_kind ON events(task_id,kind,created_at)")

    def owner(self, owner_scope):
        """Resolve only the trusted gateway scope, never a client query/header."""
        if not self.require_owner:
            return None
        if not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope):
            raise PermissionError("账户关联不可用，请重新登录。")
        return owner_scope

    def tasks(self, identity, captured, owner_scope=None):
        self.store.identity(identity)
        with self.store.connection() as db:
            # Filter before the recent-task limit: another owner's newer tasks
            # must neither hide this owner's tasks nor affect truncation.
            owner_filter = " AND EXISTS (SELECT 1 FROM task_principals p WHERE p.task_id=tasks.id AND p.owner_scope=?)" if owner_scope is not None else ""
            rows = db.execute("""SELECT id,run_id,status,attempt,created_at,updated_at,
                CASE WHEN error IS NOT NULL AND error != '' THEN 1 ELSE 0 END AS error_present
                FROM tasks WHERE identity_id=?""" + owner_filter + " ORDER BY created_at DESC,id DESC LIMIT 31",
                (identity, owner_scope) if owner_scope is not None else (identity,)).fetchall()
            result = []
            kinds = tuple(sorted(EVENTS))
            for row in rows[:30]:
                event = db.execute("SELECT kind,created_at FROM events WHERE task_id=? AND kind IN (" + ",".join("?" for _ in kinds) + ") ORDER BY created_at DESC,id DESC LIMIT 1", (row["id"], *kinds)).fetchone()
                state = row["status"] if row["status"] in TASK_STATES else "unknown"
                phase_at = stamp(event["created_at"] if event else row["created_at"])
                elapsed = max(0, int(captured - datetime.fromisoformat(phase_at).timestamp())) if phase_at else None
                error = ERRORS.get(state) or ("operation_failed" if row["error_present"] else None)
                if event and event["kind"] == "stop_unconfirmed":
                    error = "stop_unconfirmed"
                result.append({"task_id": reference(row["id"]), "run_id": reference(row["run_id"]), "phase": state,
                    "attempt": max(0, min(int(row["attempt"] or 0), 100000)), "created_at": stamp(row["created_at"]),
                    "record_updated_at": stamp(row["updated_at"]), "last_state_event_at": phase_at,
                    "seconds_without_state_change": elapsed,
                    "needs_progress_check": state in {"starting", "running", "stopping"} and elapsed is not None and elapsed >= LONG_PHASE_SECONDS,
                    "error_category": error})
        return {"items": result, "truncated": len(rows) > 30, "limit": 30, "long_phase_seconds": LONG_PHASE_SECONDS}

    async def snapshot(self, identity, deployment="local", *, owner_scope=None):
        """Internal sampler may collect the identity; public callers resolve owner().

        Health history stores trusted principals and projects each reader's tasks.
        Its internal collection must not inherit one public request's owner scope.
        """
        captured = self.clock()
        tasks = await asyncio.to_thread(self.tasks, identity, captured, owner_scope)
        captured_at = datetime.fromtimestamp(captured, timezone.utc).isoformat()
        try:
            runtime = {**runtime_summary(await asyncio.to_thread(lambda: self.runtime_for(identity).status())), "state": "observed"}
        except Exception:
            runtime = {**runtime_summary(None), "state": "unavailable"}
        runtime["observed_at"] = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()
        probe = {"state": "not_observed", "observed_at": None}
        if self.probe_for:
            try:
                value = await asyncio.wait_for(self.probe_for(identity), self.probe_timeout)
                state = value.get("state") if isinstance(value, dict) else None
                probe["state"] = state if isinstance(state, str) and state in PROBE_STATES else "unavailable"
            except TimeoutError:
                probe["state"] = "timeout"
            except Exception:
                probe["state"] = "unavailable"
            # This is an actual point-in-time request, never a continuous heartbeat.
            probe["observed_at"] = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()
        try:
            devices = device_summary(await asyncio.to_thread(self.devices_for, identity) if self.devices_for else None)
        except Exception:
            devices = {"state": "unavailable", "items": [], "truncated": False}
        devices["observed_at"] = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat() if self.devices_for else None
        try:
            service_version = version("wearing")
        except PackageNotFoundError:
            service_version = None
        return {"schema": 1, "report_id": uuid.uuid4().hex, "identity_id": identity, "captured_at": captured_at,
                "service": {"state": "reachable", "version": service_version if service_version and re.fullmatch(r"\d+(?:\.\d+){1,3}", service_version) else None,
                            "deployment": deployment if deployment in {"local", "cloud", "synthetic"} else "unknown"},
                "runtime": runtime, "engine_probe": probe, "devices": devices, "tasks": tasks}
