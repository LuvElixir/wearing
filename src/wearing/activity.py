"""A durable read receipt over existing progress; never an execution queue."""

import hashlib
import json
import re

from .confirmations import card_for
from .goals import parse_report
from .store import DEFAULT_IDENTITY, Store, now


class ActivityError(ValueError):
    pass


def _json(value, fallback=None):
    if not isinstance(value, str):
        return value if value is not None else fallback
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def _brief(value, limit=400):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _report_summary(output, report=None):
    parsed = parse_report(output) if output else None
    parsed = parsed or report
    if isinstance(parsed, dict) and isinstance(parsed.get("summary"), str):
        summary = parsed["summary"]
        if isinstance(parsed.get("next_step"), str) and parsed["next_step"].strip():
            summary += " 下一步：" + parsed["next_step"]
        return _brief(summary)
    text = (output or "").strip()
    # Structured output is opened in its detail view, never poured into a feed.
    if text.startswith(("{", "[", "```")):
        return "结果已返回，打开查看详情。"
    return _brief(text)


class ActivityBook:
    def __init__(self, store: Store):
        self.store = store
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS activity_reads (
                identity_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
                version TEXT NOT NULL, seen_at TEXT NOT NULL,
                PRIMARY KEY(identity_id,task_id))""")

    def _items(self, db, identity_id):
        tasks = [dict(row) for row in db.execute(
            "SELECT * FROM tasks WHERE identity_id=?", (identity_id,))]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        reads = {row[0]: row[1] for row in db.execute(
            "SELECT task_id,version FROM activity_reads WHERE identity_id=?", (identity_id,))}
        messages = {row[0] for row in db.execute(
            "SELECT m.task_id FROM messages m JOIN tasks t ON t.id=m.task_id WHERE t.identity_id=?", (identity_id,))}
        goals, reports, schedules, cards, handoffs = {}, {}, set(), {}, {}
        if "message_handoffs" in tables:
            handoffs = {row["task_id"]: dict(row) for row in db.execute(
                "SELECT * FROM message_handoffs WHERE identity_id=?", (identity_id,))}
        if {"personal_goals", "goal_steps"} <= tables:
            for row in db.execute("""SELECT s.task_id,s.goal_id,s.report FROM goal_steps s
                JOIN personal_goals g ON g.id=s.goal_id WHERE g.identity_id=?""", (identity_id,)):
                goals[row["task_id"]] = row["goal_id"]
                reports[row["task_id"]] = _json(row["report"])
        if {"personal_goals", "goal_messages"} <= tables:
            for row in db.execute("""SELECT m.task_id,m.goal_id,m.queued FROM goal_messages m
                JOIN personal_goals g ON g.id=m.goal_id WHERE g.identity_id=?""", (identity_id,)):
                goals[row["task_id"]] = row["goal_id"]
                if row["queued"] and row["task_id"] not in handoffs:
                    handoffs[row["task_id"]] = {"state": "queued", "blocked_reason": "等待前面的运行结束或完成核对。"}
        if {"personal_schedules", "schedule_occurrences"} <= tables:
            schedules = {row[0] for row in db.execute("""SELECT o.task_id FROM schedule_occurrences o
                JOIN personal_schedules s ON s.id=o.schedule_id WHERE s.identity_id=?""", (identity_id,))}
        if "confirmation_cards" in tables:
            for row in db.execute("""SELECT c.* FROM confirmation_cards c JOIN tasks t ON t.id=c.task_id
                WHERE t.identity_id=? ORDER BY c.created_at,c.request_id""", (identity_id,)):
                cards.setdefault(row["task_id"], []).append(dict(row))
        return [self._item(task, goals.get(task["id"]), reports.get(task["id"]),
                           task["id"] in schedules, task["id"] in messages,
                           cards.get(task["id"], []), reads.get(task["id"]), handoffs.get(task["id"])) for task in tasks]

    @staticmethod
    def _item(task, goal_id, report, scheduled, message, cards, read_version, handoff=None):
        status = task["status"]
        approval = _json(task.get("approval"), {}) or {}
        approval = approval if isinstance(approval, dict) else {}
        request_id = approval.get("request_id")
        receipt = next((c for c in reversed(cards) if c["request_id"] == request_id), None)
        if status != "waiting_for_approval":
            receipt = receipt or (cards[-1] if cards else None)
        receipt_state = receipt["state"] if receipt else approval.get("card_state")
        card = _json(receipt["card"], {}) if receipt else (card_for(approval) if approval else {})
        card = card if isinstance(card, dict) else {}
        output = task.get("output") or ""
        result_summary = _report_summary(output, report)
        error = _brief(task.get("error"))
        bucket, label, summary = "attention", "状态待核对", "状态尚不明确，打开查看原任务。"
        if status == "draft":
            label, summary = "尚未开始", "内容已保存，还没有交给 Wearing 执行。"
            if handoff and handoff["state"] in {"queued", "blocked"}:
                # A normal queue is accepted work, not a user decision or a run.
                bucket = "attention" if handoff["state"] == "blocked" else "waiting"
                label = "排队等待核对" if handoff["state"] == "blocked" else "已排队"
                summary = "已接收排队，尚未开始执行。" + (handoff.get("blocked_reason") or "")
        elif status == "waiting_for_approval":
            if approval.get("card_invalid") or (request_id and not card):
                label, summary = "确认信息待核对", "确认内容已变化或不完整，尚未执行这一步。"
            elif receipt_state in {"sending", "unknown"}:
                label, summary = "确认送达待核对", "确认是否送达还不明确，请查看原运行；不会重复提交。"
            elif receipt_state == "expired":
                label, summary = "确认已过期", "这张确认已结束，不能继续使用旧卡片。"
            elif receipt_state == "answered":
                bucket, label, summary = "active", "正在核对接续", "已记录你的决定，尚待原运行返回后续状态。"
            elif request_id and not approval.get("card_invalid"):
                label, summary = "等你确认", _brief(card.get("action")) or "有一步需要你决定，打开查看确认卡片。"
            else:
                label, summary = "确认信息待核对", "运行正在等待确认，打开查看当前状态。"
        elif status == "connection_lost":
            label, summary = "连接待核对", "暂时无法核对原运行的进展，不会自动重发任务。"
        elif status == "ambiguous":
            label, summary = "运行待核对", "还不能确定原任务是否已经开始，不会自动重发。"
        elif status in {"starting", "running", "stopping"}:
            bucket = "active"
            label = {"starting": "正在交接", "running": "正在推进", "stopping": "正在停止"}[status]
            summary = {"starting": "上次记录：正在向执行端交接这件事。", "running": "上次记录：执行中。结果返回后会保留在这里。",
                       "stopping": "上次记录：已请求停止，尚待执行端返回状态。"}[status]
        elif status in {"completed_unverified", "verified", "failed", "stopped", "closed_by_user"}:
            bucket = "results"
            label = {"completed_unverified": "结果已返回", "verified": "已核对", "failed": "执行未完成",
                     "stopped": "已停止", "closed_by_user": "已结案"}[status]
            summary = {
                "completed_unverified": result_summary or "执行端已返回结果，实际效果尚待核对。",
                "verified": _brief(task.get("verification_note")) or result_summary or "已记录你的结果核对。",
                "failed": error or result_summary or "本次执行未完成，打开查看已保留的进展。",
                "stopped": result_summary or "本次执行已停止，已保存的内容仍保留。",
                "closed_by_user": _brief(task.get("verification_note")) or "已按你的说明结案。",
            }[status]
            if status == "stopped" and handoff and handoff["state"] == "cancelled":
                label, summary = "已撤回", "这条排队消息已撤回，没有开始执行；原话仍保留。"
        semantic = {"status": status, "title": task["title"], "output": output, "error": task.get("error"),
                    "verification_note": task.get("verification_note"), "goal_id": goal_id,
                    "handoff": {k: (handoff or {}).get(k) for k in ("state", "blocked_reason")},
                    "report": parse_report(output) or report, "approval": {k: approval.get(k) for k in
                        ("request_id", "kind", "card_invalid", "command", "description")},
                    "receipt": {k: receipt.get(k) for k in ("request_id", "state", "choice", "card")} if receipt else None}
        version = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        updated_at = max(task["updated_at"], (receipt or {}).get("answered_at") or "",
                         (receipt or {}).get("created_at") or "")
        return {"task_id": task["id"], "goal_id": goal_id,
                "source": "goal" if goal_id else "schedule" if scheduled else "conversation" if message else "task",
                "bucket": bucket, "status": status, "label": label, "title": _brief(task["title"], 120),
                "summary": _brief(summary), "version": version, "updated_at": updated_at,
                "unread": bucket == "results" and (handoff or {}).get("state") != "cancelled" and read_version != version}

    def snapshot(self, identity_id=DEFAULT_IDENTITY):
        self.store.identity(identity_id)
        with self.store.connection() as db:
            db.execute("BEGIN")
            items = self._items(db, identity_id)
        # Stable passes keep newest first within each section, and old unseen
        # results ahead of new results the user has already reviewed.
        items.sort(key=lambda item: (item["updated_at"], item["task_id"]), reverse=True)
        items.sort(key=lambda item: ({"attention": 0, "active": 1, "waiting": 2, "results": 3}[item["bucket"]],
                                     not item["unread"] if item["bucket"] == "results" else False))
        return {"checked_at": now(), "total": len(items), "unread": sum(item["unread"] for item in items),
                "counts": {bucket: sum(item["bucket"] == bucket for item in items)
                           for bucket in ("attention", "active", "waiting", "results")},
                "has_more": len(items) > 20, "items": items[:20]}

    def acknowledge(self, identity_id, seen):
        self.store.identity(identity_id)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = {item["task_id"]: item for item in self._items(db, identity_id)}
            if any(entry["task_id"] not in current for entry in seen):
                raise ActivityError("这条进展不属于当前身份或已经不存在，请刷新后重试。")
            for entry in seen:
                item = current[entry["task_id"]]
                if item["bucket"] != "results" or item["version"] != entry["version"]:
                    continue
                db.execute("""INSERT INTO activity_reads VALUES(?,?,?,?)
                    ON CONFLICT(identity_id,task_id) DO UPDATE SET version=excluded.version,seen_at=excluded.seen_at
                    WHERE activity_reads.version != excluded.version""",
                           (identity_id, item["task_id"], item["version"], now()))
        return self.snapshot(identity_id)
