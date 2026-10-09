import hashlib
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from wearing.app import create_app
from wearing.artifacts import ArtifactBook, ArtifactDraft, ArtifactError, MAX_HTML_BYTES
from wearing.artifact_tools import dispatch
from wearing.config import Settings
from wearing.store import Store

HTML = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body><button onclick="this.textContent=42">调整</button></body></html>'


def setup(store, identity="daily"):
    book = ArtifactBook(store)
    task = store.create_message("做一个可调整的结果", identity)
    store.update(task["id"], status="running", run_id="run_" + task["id"])
    root = book.workspace(identity)
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.html").write_text(HTML)
    return book, task, ArtifactDraft(path="result.html", title="比较结果", summary="测试数据，仅用于验证交互", sources=["用户提供的测试数据"])


def test_publish_is_immutable_idempotent_and_bound_to_real_run(tmp_path):
    store = Store(tmp_path / "wearing.sqlite3")
    book, task, draft = setup(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.publish("daily", draft, "once"), range(4)))
    assert len({r["id"] for r in results}) == 1
    item = results[0]
    assert item["task_id"] == task["id"]
    assert item["checks"] == {"file": "verified", "render": "not_verified", "content": "not_verified"}
    (book.workspace("daily") / "result.html").write_text(HTML.replace("42", "100"))
    assert book.get("daily", item["id"], content=True)[1] == HTML.encode()
    with pytest.raises(ArtifactError, match="不同内容"):
        book.publish("daily", draft, "once")
    new = book.publish("daily", draft.model_copy(update={"previous_id": item["id"]}), "two")
    assert new["revision"] == 2 and new["family_id"] == item["id"]
    with pytest.raises(ArtifactError, match="已有更新"):
        book.publish("daily", draft.model_copy(update={"previous_id": item["id"]}), "three")
    assert len(ArtifactBook(Store(store.path)).list("daily", task["id"])) == 2
    store.update(task["id"], status="completed_unverified")
    with pytest.raises(ArtifactError, match="正在执行"):
        book.publish("daily", draft, "no-run")


def test_source_path_is_canonical_internal_and_old_rows_survive_concurrent_migration(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    book, _, draft = setup(store)
    prior = book.publish('daily', draft, 'legacy')
    with store.connection() as db:
        assert db.execute('SELECT source_path FROM artifacts WHERE id=?', (prior['id'],)).fetchone()[0] == 'result.html'
        db.execute('ALTER TABLE artifacts DROP COLUMN source_path')
    with ThreadPoolExecutor(max_workers=4) as pool:
        reopened = list(pool.map(lambda _: ArtifactBook(store), range(8)))
    assert all(instance.get('daily', prior['id']) == prior for instance in reopened)
    # A replay retains the original row and does not guess/backfill provenance.
    assert book.publish('daily', draft, 'legacy') == prior
    with store.connection() as db:
        assert db.execute('SELECT source_path FROM artifacts WHERE id=?', (prior['id'],)).fetchone()[0] is None
    root = book.workspace('daily'); (root / 'nested').mkdir()
    (root / 'nested' / 'result.html').write_text(HTML)
    current = book.publish('daily', draft.model_copy(update={'path': './nested//result.html'}), 'new')
    with store.connection() as db:
        assert db.execute('SELECT source_path FROM artifacts WHERE id=?', (current['id'],)).fetchone()[0] == 'nested/result.html'
    assert 'source_path' not in current and 'path' not in current
    assert 'source_path' not in book.get('daily', current['id'])
    assert all('source_path' not in item for item in book.list('daily'))


@pytest.mark.parametrize("path", ["../outside.html", "/tmp/outside.html", "bad\\path.html", "missing.html", "image.svg", "link.html"])
def test_invalid_paths_and_symlinks_cannot_publish(tmp_path, path):
    book, _, draft = setup(Store(tmp_path / "wearing.sqlite3"))
    (tmp_path / "outside.html").write_text(HTML)
    (book.workspace("daily") / "link.html").symlink_to(tmp_path / "outside.html")
    (book.workspace("daily") / "image.svg").write_text(HTML)
    with pytest.raises(ArtifactError):
        book.publish("daily", draft.model_copy(update={"path": path}), "bad")
    assert book.list("daily") == []


@pytest.mark.parametrize("raw", [b"", b"x" * (MAX_HTML_BYTES + 1), b"\xff<html></html>", b"<script>alert(1)</script>"])
def test_unusable_files_not_reported_as_results(tmp_path, raw):
    book, _, draft = setup(Store(tmp_path / "wearing.sqlite3"))
    (book.workspace("daily") / "result.html").write_bytes(raw)
    with pytest.raises(ArtifactError):
        book.publish("daily", draft, "invalid")
    assert not book.list("daily")


def test_tools_are_scoped_and_checks_detect_corruption(tmp_path):
    store = Store(tmp_path / "wearing.sqlite3")
    book, _, draft = setup(store)
    item = dispatch(store, "daily", "artifact_publish", {"artifact": draft.model_dump(), "request_key": "one"})
    assert dispatch(store, "daily", "artifact_read", {"artifact_id": item["id"]})["html"] == HTML
    assert dispatch(store, "daily", "artifact_list", {})["items"][0]["id"] == item["id"]
    other = store.save_identity("另一身份", "", "international")["id"]
    assert not book.list(other)
    with pytest.raises(ArtifactError):
        book.get(other, item["id"], content=True)
    _, _, other_draft = setup(store, other)
    with pytest.raises(ArtifactError):
        book.publish(other, other_draft.model_copy(update={"previous_id": item["id"]}), "foreign")
    with pytest.raises(ValidationError):
        ArtifactDraft.model_validate({**draft.model_dump(), "identity_id": other})
    with store.connection() as db:
        db.execute("UPDATE artifacts SET html=? WHERE id=?", (b"changed", item["id"]))
    with pytest.raises(ArtifactError, match="校验"):
        book.get("daily", item["id"], content=True)


async def test_http_results_conversation_download_and_preview_boundary(tmp_path):
    app = create_app(Settings(tmp_path))
    book, task, draft = setup(app.state.store)
    item = book.publish("daily", draft, "one")
    app.state.store.update(task["id"], status="completed_unverified", output="可以展开看看")
    other = app.state.store.save_identity("别的身份", "", "international")["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        conversation = (await client.get("/api/conversation")).json()
        assert conversation[0]["turn"]["artifacts"][0]["id"] == item["id"]
        assert "html" not in conversation[0]["turn"]["artifacts"][0]
        preview = await client.get(f'/api/artifacts/{item["id"]}/preview')
        assert preview.status_code == 200 and preview.text == HTML
        csp = preview.headers["content-security-policy"]
        assert "sandbox allow-scripts" in csp and "allow-same-origin" not in csp
        assert "connect-src 'none'" in csp and "frame-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp and "form-action 'none'" in csp
        assert "camera=()" in preview.headers["permissions-policy"]
        assert preview.headers["cache-control"] == "no-store"
        main = await client.get("/")
        assert "script-src 'self'" in main.headers["content-security-policy"]
        assert "unsafe-inline" not in main.headers["content-security-policy"]
        download = await client.get(f'/api/artifacts/{item["id"]}/download')
        assert "attachment" in download.headers["content-disposition"]
        assert hashlib.sha256(download.content).hexdigest() == item["sha256"]
        for suffix in ("", "/preview", "/download"):
            assert (await client.get(f'/api/artifacts/{item["id"]}{suffix}', params={"identity": other})).status_code == 404
        assert not (await client.get("/api/artifacts", params={"identity": other})).json()["items"]
        assert (await client.get(f'/api/artifacts/{item["id"]}/preview', headers={"Origin": "null"})).status_code == 403
    await app.state.service.hermes.close()


def test_design_guidance_is_medium_specific_and_does_not_publish(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    book = ArtifactBook(store)
    outputs = {kind: dispatch(store, 'daily', 'artifact_design_guide', {'presentation': kind})
               for kind in ('dashboard', 'diagram', 'interactive', 'explainer_video')}
    assert len({tuple(value['composition']) for value in outputs.values()}) == 4
    for value in outputs.values():
        assert value['verification'] == 'guidance_only_not_a_quality_verdict'
        assert value['review_cases'] and value['authoring_review']
    assert outputs['explainer_video']['delivery'] == 'planning_only'
    assert outputs['explainer_video']['starter_css'] is None
    assert outputs['explainer_video']['starter_js'] is None
    assert outputs['explainer_video']['controls'] is None
    assert '不支持视频' in outputs['explainer_video']['capability_note']
    assert outputs['interactive']['delivery'] == 'self_contained_html'
    assert 'prefers-reduced-motion' in outputs['interactive']['starter_css']
    outputs['dashboard']['composition'].clear()
    assert dispatch(store, 'daily', 'artifact_design_guide', {'presentation': 'dashboard'})['composition']
    with pytest.raises(ArtifactError):
        dispatch(store, 'daily', 'artifact_design_guide', {'presentation': 'unsupported'})
    assert book.list('daily') == []
