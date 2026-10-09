"""Small, run-scoped receipts from Hermes' native web tool progress events.

No fetching, provider routing or second tool loop lives here. This module also
runs in the managed engine interpreter, so it uses only the standard library.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import ipaddress
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, parse_qsl

MAX_RECEIPTS = 200


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        host = url.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        if any(any(word in key.lower() for word in ("token", "secret", "password", "signature", "api_key", "apikey", "credential"))
               for key, _ in parse_qsl(url.query)):
            return None
        return value
    except ValueError:
        return None


def receipt_items(tool, event, args=None, result=None, failed=False):
    """Allowlist metadata only; page body and provider internals never enter UI."""
    if tool not in {"web_search", "web_extract"}:
        return []
    stamp = datetime.now(timezone.utc).isoformat()
    base = {"tool": tool, "observed_at": stamp}
    if event == "tool.started":
        query = (args or {}).get("query")
        return [{**base, "status": "query", "title": query[:500]}] if tool == "web_search" and isinstance(query, str) else []
    if event != "tool.completed":
        return []
    try:
        data = json.loads(result) if isinstance(result, str) else result
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, TypeError):
        return [{**base, "status": "failed", "title": "工具没有返回可读取的来源记录"}]
    if failed or data.get("error") or data.get("success") is False:
        return [{**base, "status": "failed", "title": "检索服务未返回可用结果，可稍后重试或换一个来源"}]
    search_data = data.get("data")
    rows = data.get("results") if tool == "web_extract" else search_data.get("web") if isinstance(search_data, dict) else None
    if not isinstance(rows, list):
        return [{**base, "status": "failed", "title": "工具返回的来源格式无法识别"}]
    items = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        url = public_url(row.get("url"))
        if not url:
            continue
        status = "found" if tool == "web_search" else "read" if row.get("content") and not row.get("error") else "failed"
        items.append({**base, "status": status, "url": url,
                      "title": str(row.get("title") or urlsplit(url).hostname)[:300],
                      "cached": bool(row.get("cached")),
                      "detail": ("地址被网络安全检查拦截" if "Blocked:" in str(row.get("error")) else "页面未能读取，可能受站点访问限制或检索服务影响") if status == "failed" else ""})
    return items or [{**base, "status": "empty", "title": "这次没有返回可展示的公开来源"}]


class ResearchBook:
    def __init__(self, home):
        self.path = Path(home) / "wearing-research.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Research store must stay in this identity home")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS research (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, item TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS research_run ON research(run_id,id)")
            db.execute("CREATE TABLE IF NOT EXISTS research_overflow (run_id TEXT PRIMARY KEY, count INTEGER NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, run_id, items):
        if not run_id or not items:
            return
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM research WHERE run_id=?", (run_id,)).fetchone()[0]
            keep = items[:max(0, MAX_RECEIPTS - count)]
            db.executemany("INSERT INTO research(run_id,item) VALUES(?,?)", [(run_id, json.dumps(item, ensure_ascii=False)) for item in keep])
            if len(keep) < len(items):
                db.execute("INSERT INTO research_overflow VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET count=count+excluded.count",
                           (run_id, len(items) - len(keep)))

    def snapshot(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT item FROM research WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
            overflow = db.execute("SELECT count FROM research_overflow WHERE run_id=?", (run_id,)).fetchone()
        return {"items": [json.loads(row[0]) for row in rows], "omitted": overflow[0] if overflow else 0}
