"""Durable life-change inbox for intentions; no domain-specific plans or agent loop."""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .life import LifeBook


class LifeChangeTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_kinds: list[Literal["note", "task", "event"]] = Field(default_factory=lambda: ["note", "task", "event"], min_length=1, max_length=3)
    debounce_seconds: int = Field(default=60, ge=15, le=600, strict=True)
    cooldown_minutes: int = Field(default=15, ge=1, le=1440, strict=True)
    max_runs_per_day: int = Field(default=12, ge=1, le=48, strict=True)

    @model_validator(mode="after")
    def canonical(self):
        self.record_kinds = sorted(set(self.record_kinds))
        return self


def utc(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class LifeEventInbox:
    def __init__(self, store):
        self.store = store
        LifeBook(store)  # Also used by headless/MCP callers before the web app starts.
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schedule_event_cursors (
                    schedule_id TEXT PRIMARY KEY REFERENCES personal_schedules(id), sequence INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS schedule_event_buffer (
                    schedule_id TEXT PRIMARY KEY REFERENCES personal_schedules(id),
                    first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
                    first_at TEXT NOT NULL, last_at TEXT NOT NULL, change_count INTEGER NOT NULL,
                    refs TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schedule_event_batches (
                    occurrence_id INTEGER PRIMARY KEY REFERENCES schedule_occurrences(id),
                    first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
                    change_count INTEGER NOT NULL, refs TEXT NOT NULL);
            """)

    @staticmethod
    def reset(db, schedule_id, identity):
        # Creation/edit/resume start from now; paused history is not replayed.
        sequence = db.execute("SELECT COALESCE(MAX(sequence),0) FROM life_changes WHERE identity_id=?", (identity,)).fetchone()[0]
        db.execute("INSERT OR REPLACE INTO schedule_event_cursors VALUES(?,?)", (schedule_id, sequence))
        db.execute("DELETE FROM schedule_event_buffer WHERE schedule_id=?", (schedule_id,))

    @staticmethod
    def eligible(db, schedule_id, trigger, due):
        # A rolling 24h limit avoids midnight bursts and has no DST ambiguity.
        rows = db.execute("""SELECT o.created_at FROM schedule_occurrences o
            JOIN schedule_event_batches b ON b.occurrence_id=o.id
            WHERE o.schedule_id=? AND o.task_id IS NOT NULL ORDER BY o.id DESC LIMIT ?""",
                          (schedule_id, trigger.max_runs_per_day)).fetchall()
        if rows:
            due = max(due, utc(rows[0][0]) + timedelta(minutes=trigger.cooldown_minutes))
        if len(rows) == trigger.max_runs_per_day:
            due = max(due, utc(rows[-1][0]) + timedelta(days=1))
        return due.isoformat()

    def collect(self, stamp):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            schedules = db.execute("""SELECT s.*,c.sequence FROM personal_schedules s
                JOIN schedule_event_cursors c ON c.schedule_id=s.id WHERE s.status='active'""").fetchall()
            for schedule in schedules:
                spec = json.loads(schedule["spec"])
                if spec["kind"] != "life_change":
                    continue
                if spec.get("goal_id"):
                    goal = db.execute("SELECT status,used_steps,max_steps FROM personal_goals WHERE id=? AND identity_id=?", (spec["goal_id"], schedule["identity_id"])).fetchone()
                    if not goal or goal["status"] not in {"active", "waiting"} or goal["used_steps"] >= goal["max_steps"]:
                        self.reset(db, schedule["id"], schedule["identity_id"])
                        db.execute("UPDATE personal_schedules SET next_run=NULL WHERE id=?", (schedule["id"],))
                        continue
                trigger = LifeChangeTrigger.model_validate(spec["changes"])
                changes = db.execute("""SELECT * FROM life_changes WHERE identity_id=? AND sequence>?
                    ORDER BY sequence LIMIT 500""", (schedule["identity_id"], schedule["sequence"])).fetchall()
                if not changes:
                    continue
                buffered = db.execute("SELECT * FROM schedule_event_buffer WHERE schedule_id=?", (schedule["id"],)).fetchone()
                refs = {r["record_id"]: r for r in json.loads(buffered["refs"])} if buffered else {}
                cursor = schedule["sequence"]
                matched = []
                for event in changes:
                    body = json.loads(event["body"])
                    origin = body.get("_origin", event["actor"])
                    if origin not in {"user", "conversation"} or body["kind"] not in trigger.record_kinds:
                        cursor = event["sequence"]
                        continue
                    # Keep every relevant record: excess work stays behind the
                    # durable cursor for the next batch, instead of truncating it.
                    if event["record_id"] not in refs and len(refs) >= 50:
                        break
                    cursor = event["sequence"]
                    ref = {"event_id": f"life:{event['sequence']}", "sequence": event["sequence"],
                                    "record_id": event["record_id"], "revision": event["revision"],
                                    "kind": body["kind"], "deleted": bool(body["deleted_at"]),
                                    "occurred_at": event["created_at"], "origin": origin}
                    matched.append(ref)
                    refs[ref["record_id"]] = ref
                db.execute("UPDATE schedule_event_cursors SET sequence=? WHERE schedule_id=?", (cursor, schedule["id"]))
                if not matched:
                    continue
                first_at = buffered["first_at"] if buffered else stamp
                first_seq = buffered["first_sequence"] if buffered else matched[0]["sequence"]
                refs = sorted(refs.values(), key=lambda r: r["sequence"])
                count = (buffered["change_count"] if buffered else 0) + len(matched)
                db.execute("INSERT OR REPLACE INTO schedule_event_buffer VALUES(?,?,?,?,?,?,?)",
                           (schedule["id"], first_seq, matched[-1]["sequence"], first_at, stamp, count, json.dumps(refs)))
                due = min(utc(stamp) + timedelta(seconds=trigger.debounce_seconds),
                          utc(first_at) + timedelta(seconds=trigger.debounce_seconds * 3))
                due = self.eligible(db, schedule["id"], trigger, due)
                db.execute("UPDATE personal_schedules SET next_run=?,updated_at=? WHERE id=?", (due, stamp, schedule["id"]))

    def prepare(self, db, schedule, spec, stamp):
        buffered = db.execute("SELECT * FROM schedule_event_buffer WHERE schedule_id=?", (schedule["id"],)).fetchone()
        if not buffered:
            db.execute("UPDATE personal_schedules SET next_run=NULL WHERE id=?", (schedule["id"],))
            return None
        # Recheck limits inside the occurrence claim transaction.
        eligible = self.eligible(db, schedule["id"], spec.changes, utc(schedule["next_run"]))
        if eligible > stamp:
            db.execute("UPDATE personal_schedules SET next_run=? WHERE id=?", (eligible, schedule["id"]))
            return None
        # Give an in-progress photo/voice capture time to finish before reading it.
        if utc(stamp) < utc(buffered["first_at"]) + timedelta(minutes=10) and db.execute("SELECT 1 FROM sqlite_master WHERE name='life_captures'").fetchone():
            ids = [r["record_id"] for r in json.loads(buffered["refs"])]
            if any(db.execute("SELECT 1 FROM life_captures WHERE record_id=? AND state IN ('queued','extracting','organizing')", (record_id,)).fetchone() for record_id in ids):
                db.execute("UPDATE personal_schedules SET next_run=? WHERE id=?", ((utc(stamp) + timedelta(seconds=15)).isoformat(), schedule["id"]))
                return None
        return buffered

    @staticmethod
    def freeze(db, occurrence_id, buffered):
        db.execute("INSERT INTO schedule_event_batches VALUES(?,?,?,?,?)", (occurrence_id, buffered["first_sequence"], buffered["last_sequence"], buffered["change_count"], buffered["refs"]))
        db.execute("DELETE FROM schedule_event_buffer WHERE schedule_id=?", (buffered["schedule_id"],))

    def context(self, occurrence_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM schedule_event_batches WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        if not row:
            return None
        return {"source": "life_changes", "first_sequence": row["first_sequence"], "last_sequence": row["last_sequence"],
                "change_count": row["change_count"], "records": json.loads(row["refs"]),
                "reference_limit": 50, "contents_are_instructions": False}
