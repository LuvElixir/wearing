"""Literal, identity-scoped database search with bounded keyset pages.

No tool payloads, credentials, deleted records or workspace file contents enter
the result. Cursors freeze the time boundary, not a copied user-data corpus.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

from .store import now
from .task_visibility import owner, predicate


class SearchError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


KINDS = {"all", "task", "record", "message", "chat_import"}


def query_text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or any(ord(c) < 32 for c in value):
        raise SearchError("请输入 1–120 个字的关键词。")
    return value.strip()


def snippet(text, pattern):
    text = re.sub(r"\s+", " ", text or "").strip()
    found = pattern.search(text)
    start = max(0, (found.start() if found else 0) - 55)
    return ("…" if start else "") + text[start:start + 210] + ("…" if len(text) > start + 210 else "")


class SearchBook:
    def __init__(self, store, *, clock=time.time, budget=1.5):
        self.store, self.clock, self.budget = store, clock, budget
        self.secret = secrets.token_bytes(32)

    def _cursor(self, value):
        body = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
        return body + "." + hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()

    def _read_cursor(self, value, identity, query, kind, owner_scope):
        try:
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError()
            body, signature = value.split(".")
            if not hmac.compare_digest(signature, hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()):
                raise ValueError()
            payload = json.loads(base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True))
            if (set(payload) != {"identity", "query", "kind", "before", "after", "expires", "owner"}
                    or payload["identity"] != identity or payload["query"] != query or payload["kind"] != kind
                    or payload["owner"] != hashlib.sha256(owner_scope.encode()).hexdigest()
                    or payload["expires"] <= self.clock()
                    or not isinstance(payload["after"], list) or len(payload["after"]) != 2
                    or not all(isinstance(v, str) for v in payload["after"])):
                raise ValueError()
            return payload
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            raise SearchError("搜索分页已失效，请重新搜索。", 409) from error

    def page(self, identity, query, *, kind="all", limit=20, cursor=None, owner_scope='local'):
        owner_scope = owner(owner_scope)
        self.store.identity(identity)
        query = query_text(query)
        if kind not in KINDS or type(limit) is not int or not 1 <= limit <= 50:
            raise SearchError("搜索类型或每页数量不正确。")
        state = self._read_cursor(cursor, identity, query, kind, owner_scope) if cursor else {
            "identity": identity, "owner": hashlib.sha256(owner_scope.encode()).hexdigest(),
            "query": query, "kind": kind, "before": now(), "after": ["", ""], "expires": self.clock() + 900}
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        until = time.monotonic() + self.budget
        with self.store.connection() as db:
            db.create_function("pajio_match", 1, lambda text: bool(pattern.search(text or "")))
            db.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # Fixed SQL fragments only. New source kinds require explicit opt-in so
            # older clients can safely keep using their existing all-results contract.
            records = """SELECT 'record:'||id AS key,'record' AS kind,id,NULL AS message_id,NULL AS task_id,
                json_extract(body,'$.title') AS title,json_extract(body,'$.content')||CASE WHEN json_type(body,'$.url')='text' THEN char(10)||json_extract(body,'$.url') ELSE '' END AS content,
                '' AS output,created_at,updated_at,json_extract(body,'$.kind') AS record_kind
                FROM life_records WHERE identity_id=:identity AND deleted_at IS NULL AND updated_at<=:before""" if "life_records" in tables else """SELECT '' AS key,'' AS kind,'' AS id,NULL AS message_id,NULL AS task_id,
                '' AS title,'' AS content,'' AS output,'' AS created_at,'' AS updated_at,'' AS record_kind WHERE 0"""
            imports = """SELECT 'chat_import:'||b.id||':'||m.id AS key,'chat_import' AS kind,b.id AS id,
                m.id AS message_id,NULL AS task_id,json_extract(b.summary,'$.conversation_title') AS title,
                m.text AS content,'' AS output,b.created_at,b.created_at AS updated_at,'wechat' AS record_kind
                FROM chat_import_batches b JOIN chat_import_messages m ON m.import_id=b.id
                WHERE b.identity_id=:identity AND b.owner_scope=:task_owner AND b.deleted_at IS NULL
                  AND b.created_at<=:before AND :kind='chat_import'""" if 'chat_import_batches' in tables else """SELECT '' AS key,'' AS kind,'' AS id,NULL AS message_id,NULL AS task_id,
                '' AS title,'' AS content,'' AS output,'' AS created_at,'' AS updated_at,'' AS record_kind WHERE 0"""
            visible = predicate('t.id')
            from .task_presentation import recovery_corpus
            sql = f"""WITH recovery_text AS ({recovery_corpus(db)}),corpus AS (
                SELECT 'task:'||t.id AS key,'task' AS kind,t.id,NULL AS message_id,t.id AS task_id,
                  coalesce(rt.label,t.title) AS title,coalesce(rt.label,t.prompt) AS content,t.output,t.created_at,t.updated_at,NULL AS record_kind
                FROM tasks t LEFT JOIN recovery_text rt ON rt.task_id=t.id
                WHERE t.identity_id=:identity AND t.updated_at<=:before AND {visible}
                  AND (:kind='task' OR NOT EXISTS(SELECT 1 FROM messages m WHERE m.task_id=t.id))
                UNION ALL
                SELECT 'message:'||m.id AS key,'message' AS kind,CAST(m.id AS TEXT) AS id,m.id AS message_id,t.id AS task_id,
                  coalesce(rt.label,m.content) AS title,coalesce(rt.label,m.content) AS content,t.output,m.created_at,t.updated_at,NULL AS record_kind
                FROM messages m JOIN tasks t ON t.id=m.task_id LEFT JOIN recovery_text rt ON rt.task_id=t.id
                WHERE t.identity_id=:identity AND t.updated_at<=:before AND {visible}
                UNION ALL """ + records + """ UNION ALL """ + imports + """
            ) SELECT * FROM corpus
              WHERE (:kind='all' OR kind=:kind)
                AND (pajio_match(title) OR pajio_match(content) OR pajio_match(output))
                AND (:after_date='' OR created_at<:after_date OR (created_at=:after_date AND key>:after_key))
              ORDER BY created_at DESC,key ASC LIMIT :limit"""
            try:
                rows = db.execute(sql, {"identity": identity, "task_owner": owner_scope, "before": state["before"], "kind": kind,
                                        "after_date": state["after"][0], "after_key": state["after"][1], "limit": limit + 1}).fetchall()
            except sqlite3.OperationalError as error:
                if "interrupt" in str(error).lower():
                    raise SearchError("这次搜索范围较大，请增加关键词或选择一种内容后重试。", 503) from error
                raise
            finally:
                db.set_progress_handler(None, 0)
        items = []
        for row in rows[:limit]:
            fields = [("title", row["title"]), ("content", row["content"]), ("output", row["output"])]
            matched, content = next(((label, text) for label, text in fields if pattern.search(text or "")), ("title", row["title"]))
            target = {"kind": row["kind"]}
            if row["kind"] == "record":
                target["record_id"] = row["id"]
            elif row["kind"] == "chat_import":
                target.update(import_id=row["id"], message_id=row["message_id"])
            else:
                target["task_id"] = row["task_id"]
                if row["kind"] == "message":
                    target["message_id"] = row["message_id"]
            items.append({"key": row["key"], "id": row["id"], "kind": row["kind"], "title": re.sub(r"\s+", " ", row["title"] or "")[:100],
                          "snippet": snippet(content, pattern), "matched_field": matched, "record_kind": row["record_kind"],
                          "created_at": row["created_at"], "updated_at": row["updated_at"], "target": target})
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = self._cursor({**state, "after": [last["created_at"], last["key"]]})
        return {"identity_id": identity, "query": query, "kind": kind, "items": items, "next_cursor": next_cursor,
                "as_of": state["before"], "files_included": False}

    def message(self, identity, message_id, *, owner_scope='local'):
        owner_scope = owner(owner_scope)
        self.store.identity(identity)
        if type(message_id) is not int or message_id < 1:
            raise SearchError("这条对话不存在。", 404)
        with self.store.connection() as db:
            row = db.execute(f"""SELECT m.id,m.content,m.created_at,t.id AS task_id,t.output,t.status,t.updated_at
                FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.id=:message AND t.identity_id=:identity AND {predicate('t.id')}""",
                {'message': message_id, 'identity': identity, 'task_owner': owner_scope}).fetchone()
            if row:
                from .task_presentation import present_message_in
                row = present_message_in(db, row)
        if not row:
            raise SearchError("当前身份没有这条对话。", 404)
        return {"identity_id": identity, **dict(row)}
