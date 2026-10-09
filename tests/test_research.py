import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from wearing.research import ResearchBook, MAX_RECEIPTS, public_url, receipt_items
from wearing.store import Store


def test_receipts_distinguish_search_read_cache_and_failure_without_page_body():
    result = receipt_items("web_search", "tool.completed", result=json.dumps({"success": True, "data": {"web": [{"title": "官方资料", "url": "https://example.org/doc", "description": "not stored"}]}}))
    assert result[0]["status"] == "found"
    assert "not stored" not in json.dumps(result)
    pages = receipt_items("web_extract", "tool.completed", result={"results": [
        {"url": "https://example.org/doc", "content": "not stored", "cached": True},
        {"url": "https://example.org/bad", "error": "Blocked: URL targets a private or internal network address"},
    ]})
    assert [r["status"] for r in pages] == ["read", "failed"]
    assert pages[0]["cached"] is True and "observed_at" in pages[0]
    assert "拦截" in pages[1]["detail"]
    assert "not stored" not in json.dumps(pages)


@pytest.mark.parametrize("value", ["javascript:alert(1)", "https://secret@example.com", "https://example.com/?access_token=secret", "file:///private", "http://127.0.0.1/admin", "http://10.0.0.1", "http://metadata.internal", "https://[", "https://example.org/\nscript"])
def test_unsafe_display_urls_omitted(value):
    assert public_url(value) is None


@pytest.mark.parametrize("result", [None, "bad json", [], {"data": []}, {"success": False, "error": "secret raw provider diagnostics"}])
def test_malformed_and_failed_result_is_not_evidence(result):
    receipt = receipt_items("web_search", "tool.completed", result=result)
    assert receipt[0]["status"] == "failed"
    assert "secret" not in json.dumps(receipt)


def test_query_started_does_not_claim_completed_search():
    assert receipt_items("web_search", "tool.started", {"query": "安静的地方"})[0]["status"] == "query"
    assert receipt_items("terminal", "tool.completed", result="hi") == []


def test_run_and_identity_isolation_persistence_and_atomic_limit(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    book = ResearchBook(one)
    item = {"status": "found", "url": "https://example.org"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: book.record("r1", [item] * 60), range(4)))
    result = ResearchBook(one).snapshot("r1")
    assert len(result["items"]) == MAX_RECEIPTS and result["omitted"] == 240 - MAX_RECEIPTS
    assert book.snapshot("r2")["items"] == ResearchBook(two).snapshot("r1")["items"] == []
    book.record("r2", [{**item, "status": "read"}])
    assert book.snapshot("r2")["items"][0]["status"] == "read"
    assert book.path.stat().st_mode & 0o077 == 0


def test_symlink_store_refused(tmp_path):
    original = tmp_path / "original"
    original.write_text("preserve")
    (tmp_path / "wearing-research.sqlite3").symlink_to(original)
    with pytest.raises(ValueError):
        ResearchBook(tmp_path)
    assert original.read_text() == "preserve"


def test_task_receipt_survives_reload(tmp_path):
    store = Store(tmp_path / "wearing.sqlite3")
    task = store.create("test", "computer")
    record = {"items": [{"status": "read", "url": "https://example.org"}], "omitted": 0}
    store.update(task["id"], research=record)
    assert Store(store.path).get(task["id"])["research"] == record
