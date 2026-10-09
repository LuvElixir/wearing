"""Bounded traversal, cursor replay/isolation, and real read-only ASGI routes."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI, Request
from wearing.store import Store
from wearing.workspace import WorkspacePager, WorkspacePageError, file_metadata
from wearing.workspace_api import install_workspace_page_routes


def collect(pager, root, **options):
    pages, cursor = [], None
    for _ in range(200):
        page = pager.page(root, 'daily', cursor=cursor, **options)
        pages.append(page)
        cursor = page['next_cursor']
        if not cursor: return pages
    raise AssertionError('scan did not finish')


def test_large_listing_reaches_every_file_with_small_bounded_pages(tmp_path):
    for index in range(457): (tmp_path / f'file-{index:04}.txt').write_text('QA')
    pager = WorkspacePager(scan_budget=53)
    pages = collect(pager, tmp_path, limit=27)
    files = [f['path'] for page in pages for f in page['files']]
    assert len(files) == len(set(files)) == 457
    assert len(pages) > 2 and all(len(page['files']) <= 27 for page in pages)
    assert all(page['truncated'] and not page['complete'] for page in pages[:-1])
    assert pages[-1]['complete'] and pages[-1]['scanned'] == 457
    assert not pager.scans[next(iter(pager.scans))].frames
    pager.close()


def test_search_after_2000_entries_does_not_claim_early_empty(tmp_path):
    for index in range(2205): (tmp_path / f'file-{index:04}.txt').touch()
    (tmp_path / 'needle-only.md').write_text('not searched by contents')
    pager = WorkspacePager(scan_budget=90)
    pages = collect(pager, tmp_path, query='NEEDLE')
    assert [file['path'] for page in pages for file in page['files']] == ['needle-only.md']
    assert any(not page['files'] and not page['complete'] and page['next_cursor'] for page in pages)
    assert pages[-1]['complete'] and pages[-1]['scanned'] == 2206
    pager.close()


def test_folder_search_is_server_scoped_and_names_not_contents(tmp_path):
    (tmp_path/'work').mkdir(); (tmp_path/'workshop').mkdir()
    (tmp_path/'work'/'计划.md').write_text('needle content must not be read')
    (tmp_path/'work'/'Needle.txt').write_text('QA')
    (tmp_path/'workshop'/'Needle.txt').touch()
    pager = WorkspacePager()
    pages = collect(pager, tmp_path, directory='work', query='needle')
    assert [x['path'] for p in pages for x in p['files']] == ['work/Needle.txt']
    pager.close()


def test_same_cursor_retry_is_idempotent_and_bound_to_identity_root_query_directory(tmp_path):
    root=tmp_path/'one'; root.mkdir(); other=tmp_path/'two'; other.mkdir()
    for n in range(9): (root/f'{n}.txt').touch()
    pager=WorkspacePager()
    first=pager.page(root,'daily',limit=2); token=first['next_cursor']
    second=pager.page(root,'daily',limit=2,cursor=token)
    assert pager.page(root,'daily',limit=2,cursor=token)==second
    assert set(x['path'] for x in first['files']).isdisjoint(x['path'] for x in second['files'])
    for args in [(root,'work',{}),(other,'daily',{}),(root,'daily',{'query':'new'}),(root,'daily',{'directory':'new'})]:
        with pytest.raises(WorkspacePageError): pager.page(args[0],args[1],cursor=token,**args[2])
    pager.close()


def test_directory_replacement_and_completed_subdirectory_changes_invalidate(tmp_path):
    (tmp_path/'a').mkdir(); (tmp_path/'a'/'one').touch()
    (tmp_path/'b').mkdir()
    for n in range(5): (tmp_path/'b'/str(n)).touch()
    pager=WorkspacePager(); first=pager.page(tmp_path,'daily',limit=2)
    scan=next(iter(pager.scans.values()))
    watched=next(path for path in scan.watched if path)
    (tmp_path/watched/'new-file').touch()
    with pytest.raises(WorkspacePageError,match='发生变化'): pager.page(tmp_path,'daily',limit=2,cursor=first['next_cursor'])
    assert not pager.scans


def test_no_follow_symlink_fifo_or_escape_and_metadata_without_listing(tmp_path):
    root=tmp_path/'files'; root.mkdir(); outside=tmp_path/'secret'; outside.mkdir()
    (outside/'hidden').write_text('secret-canary')
    (root/'link').symlink_to(outside, target_is_directory=True)
    (root/'linked-file').symlink_to(outside/'hidden')
    os.mkfifo(root/'fifo'); (root/'safe').write_text('okay')
    pager=WorkspacePager(); pages=collect(pager,root)
    assert [f['path'] for p in pages for f in p['files']]==['safe']
    assert file_metadata(root,'safe')['size']==4
    for path in ['../secret/hidden','link/hidden','linked-file','fifo','/etc/passwd','a//b','a\\b']:
        with pytest.raises(WorkspacePageError): file_metadata(root,path)
    for path in ['../secret','link','/','a//b']:
        with pytest.raises(WorkspacePageError): pager.page(root,'daily',directory=path)
    pager.close()


def test_expiry_eviction_and_forged_tokens_fail_closed_and_release_handles(tmp_path):
    for n in range(5): (tmp_path/str(n)).touch()
    clock=[0]; pager=WorkspacePager(ttl=10,max_scans=1,clock=lambda:clock[0])
    one=pager.page(tmp_path,'daily',limit=1); old=next(iter(pager.scans.values()))
    pager.page(tmp_path,'daily',query='other')
    assert not old.frames
    with pytest.raises(WorkspacePageError): pager.page(tmp_path,'daily',cursor=one['next_cursor'])
    two=pager.page(tmp_path,'daily',limit=1); clock[0]=11
    with pytest.raises(WorkspacePageError): pager.page(tmp_path,'daily',cursor=two['next_cursor'])
    assert not pager.scans
    for token in ['../cursor','A'*43, 'x'*9999]:
        with pytest.raises(WorkspacePageError): pager.page(tmp_path,'daily',cursor=token)
    pager.close()


def test_small_scan_budget_remains_resumable_during_directory_rechecks(tmp_path):
    for n in range(12):
        (tmp_path/str(n)).mkdir(); (tmp_path/str(n)/'file').touch()
    pager=WorkspacePager(scan_budget=4)
    pages=collect(pager,tmp_path,limit=2)
    assert len([x for p in pages for x in p['files']])==12
    assert any(p['phase']=='checking' for p in pages)
    assert pages[-1]['complete']
    pager.close()


async def test_routes_use_current_identity_workspace_and_read_only_metadata(tmp_path):
    store=Store(tmp_path/'test.sqlite3'); other=store.save_identity('QA other')['id']
    roots={identity:tmp_path/identity for identity in ['daily',other]}
    for root in roots.values(): root.mkdir()
    for i in range(210): (roots['daily']/f'file{i}.md').touch()
    (roots[other]/'private.md').write_text('other identity')
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,call_next):
        request.state.identity_id=request.headers.get('X-Wearing-Identity','daily')
        return await call_next(request)
    pager=install_workspace_page_routes(app,store,lambda identity:SimpleNamespace(workspace=roots[identity]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        first=await client.get('/api/workspace/page'); assert first.status_code==200
        cursor=first.json()['next_cursor']; assert cursor
        wrong=await client.get('/api/workspace/page',params={'cursor':cursor},headers={'X-Wearing-Identity':other})
        assert wrong.status_code==409 and 'private' not in wrong.text
        second=await client.get('/api/workspace/page',params={'cursor':cursor}); assert second.status_code==200
        assert len(first.json()['files'])+len(second.json()['files'])==210
        assert (await client.get('/api/workspace/metadata',params={'path':'private.md'})).status_code==404
        assert (await client.get('/api/workspace/metadata',params={'path':'private.md'},headers={'X-Wearing-Identity':other})).json()['size']==14
        assert (await client.get('/api/workspace/page',params={'query':'x'*201})).status_code==422
    pager.close()
