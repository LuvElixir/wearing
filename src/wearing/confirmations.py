"""Human decisions ride the existing Hermes run; they never start another run."""
import asyncio
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .store import now


MARKER = "WEARING_CONFIRMATION_V1\n"


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=80)
    action: str = Field(min_length=2, max_length=1600)
    impact: str = Field(min_length=2, max_length=800)
    confirm_label: str = Field(default="确认并继续", min_length=2, max_length=20)


async def request_confirmation(context, arguments):
    card = Confirmation.model_validate(arguments).model_dump()
    try:
        result = await asyncio.wait_for(context.session.elicit_form(
            MARKER + json.dumps(card, ensure_ascii=False), {"type": "object", "properties": {}}), timeout=315)
        decision = "approved" if result.action == "accept" else "not_approved"
    except (TimeoutError, OSError):
        decision = "not_approved"
    return {"decision": decision, "card_closed": True, "action": card["action"], "impact": card["impact"],
            "next": "仅继续这张卡片说明的动作，并读取实际结果。确认不等于动作完成。" if decision == "approved"
            else "这张卡片已结束，所列动作未获批准，不执行、不换工具绕过。简短告知未执行并保留进展，然后结束本轮。不要催用户再次确认、让用户回到旧卡点击、或自行重建同一张卡；只有用户之后明确提出新意图才重新处理。"}


def card_for(approval):
    command = str(approval.get("command") or "")
    if command.startswith(MARKER):
        try:
            return Confirmation.model_validate_json(command[len(MARKER):]).model_dump()
        except ValidationError:
            return None  # An incomplete proposal must not become an actionable card.
    return {"title": "这一步，需要你确认", "action": str(approval.get("description") or "执行下方操作。")[:1600],
            "impact": "只允许当前这一次操作。", "confirm_label": "允许这一次", "command": command[:12000]}


class ConfirmationBook:
    """A durable, task/request-bound receipt. Approval is not business success."""
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS confirmation_cards (
                task_id TEXT NOT NULL REFERENCES tasks(id), request_id TEXT NOT NULL,
                run_id TEXT NOT NULL, card TEXT NOT NULL, state TEXT NOT NULL,
                choice TEXT, created_at TEXT NOT NULL, answered_at TEXT,
                PRIMARY KEY(task_id,request_id))""")

    def observe(self, task, approval):
        request = approval.get("request_id") if isinstance(approval, dict) else None
        card = card_for(approval) if request else None
        # Desktop decisions keep their existing frame/revision-bound ledger.
        if approval and approval.get("kind") == "desktop_input":
            request, card = None, None
        with self.store.connection() as db:
            db.execute("UPDATE confirmation_cards SET state='expired' WHERE task_id=? AND state='pending' AND request_id IS NOT ?",
                       (task["id"], request))
            if not request or not card:
                if request:
                    db.execute("UPDATE confirmation_cards SET state='expired' WHERE task_id=? AND request_id=? AND state='pending'", (task["id"], request))
                return approval if not request else {**approval, "card_invalid": True}
            encoded = json.dumps(card, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO confirmation_cards VALUES(?,?,?,?, 'pending',NULL,?,NULL)",
                       (task["id"], request, task["run_id"], encoded, now()))
            row = db.execute("SELECT * FROM confirmation_cards WHERE task_id=? AND request_id=?", (task["id"], request)).fetchone()
            if row["card"] != encoded or row["run_id"] != task["run_id"]:
                db.execute("UPDATE confirmation_cards SET state='expired' WHERE task_id=? AND request_id=? AND state='pending'", (task["id"], request))
                return {**approval, "card_invalid": True}
            return {**approval, "card": card, "card_state": row["state"]}

    def claim(self, task, request_id):
        approval = task.get("approval") or {}
        card = card_for(approval)
        if not card or approval.get("card_invalid"):
            return False
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return bool(db.execute("""UPDATE confirmation_cards SET state='sending' WHERE
                task_id=? AND request_id=? AND run_id=? AND card=? AND state='pending'""",
                (task["id"], request_id, task["run_id"], json.dumps(card, ensure_ascii=False, sort_keys=True))).rowcount)

    def finish(self, task_id, request_id, choice, state="answered"):
        with self.store.connection() as db:
            db.execute("UPDATE confirmation_cards SET state=?,choice=?,answered_at=? WHERE task_id=? AND request_id=? AND state='sending'",
                       (state, choice, now() if state == "answered" else None, task_id, request_id))

    def for_identity(self, identity):
        with self.store.connection() as db:
            rows = db.execute("""SELECT c.* FROM confirmation_cards c JOIN tasks t ON t.id=c.task_id
                WHERE t.identity_id=? ORDER BY c.created_at,c.request_id""", (identity,)).fetchall()
        result = {}
        for row in rows:
            item = dict(row)
            item["card"] = json.loads(item["card"])
            result.setdefault(item.pop("task_id"), []).append(item)
        return result
