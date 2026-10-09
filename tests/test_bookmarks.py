"""Synthetic bookmark lifecycle through the existing records and HTTP APIs."""
import hashlib
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from wearing.bookmarks import BookmarkBook
from wearing.bookmark_api import install_bookmark_routes
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.life_api import install_life_routes
from wearing.life_proxy import dispatch
from wearing.search import SearchBook
from wearing.store import Store


@pytest.fixture
def books(tmp_path):
    life = LifeBook(Store(tmp_path / 'bookmarks.sqlite3'))
    return life, BookmarkBook(life)


def draft(**patch):
    return LifeDraft.model_validate(dict(kind='note', title='收藏标题', content='用户自己的备注', url='https://example.com/path?a=1#read', **patch))


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,a', 'file:///tmp/a', 'pajio://login', '//example.com', 'https:example.com', 'https://u:p@example.com', 'https://@example.com', 'https://exa%6dple.com', 'https://example.com\\@evil.com', 'https://example.com/\nhi', 'https://example.com/a b', 'https://example.com/%0afoo', 'https://example.com:0', 'https://example.com:99999', 'https://', '', 4])
def test_unsafe_url_fails_before_record_write(books, url):
    life, _ = books
    with pytest.raises(ValidationError):
        LifeDraft(kind='note', title='收藏', url=url)
    assert life.snapshot('daily')['items'] == []


def test_plain_note_json_and_old_idempotent_hash_are_unchanged(books):
    life, view = books
    plain = LifeDraft(kind='note', title='以前的笔记', content='https://example.com')
    original = {'kind':'note','title':'以前的笔记','content':'https://example.com','start_at':None,'end_at':None,'timezone':'Asia/Shanghai','all_day':False,'due_at':None,'completed':False,'list_name':'待办'}
    body = json.dumps(original, ensure_ascii=False, separators=(',', ':'))
    assert plain.model_dump_json() == body
    record = life.create('daily', plain, 'legacy-request')
    with life.store.connection() as db:
        assert db.execute('SELECT request_hash FROM life_records').fetchone()[0] == hashlib.sha256(body.encode()).hexdigest()
    assert life.create('daily', plain, 'legacy-request') == record
    assert view.page('daily')['items'] == []  # Text containing a URL isn't a bookmark.


def test_complete_lifecycle_cas_retries_and_two_identities(books):
    life, view = books
    other = life.store.save_identity('工作')['id']
    record = dispatch(life, 'daily', 'life_create', {'record':draft().model_dump(), 'request_key':'share-1'})
    own = life.get('daily', record['id'])
    assert life.create('daily', draft(), 'share-1')['id'] == own['id']
    assert view.page(other)['items'] == []
    with pytest.raises(LifeError): life.update(other, own['id'], 1, {'url':'https://else.example/'})
    updated = life.update('daily',own['id'],1,{'url':'https://else.example/', 'title':'更新标题','content':'新的用户备注'},request_key='edit-1')
    assert updated['revision'] == 2
    assert life.update('daily',own['id'],1,{'url':'https://else.example/', 'title':'更新标题','content':'新的用户备注'},request_key='edit-1') == updated
    with pytest.raises(LifeError): life.update('daily',own['id'],1,{'content':'迟到的修改'})
    assert life.get('daily',own['id']) == updated
    removed = life.update('daily',own['id'],2,action='archive',request_key='archive-1')
    assert not view.page('daily')['items']
    assert view.page('daily',archived=True)['items'] == [removed]
    restored = life.update('daily',own['id'],3,action='restore',request_key='restore-1')
    assert restored['revision'] == 4 and not restored['deleted_at']
    assert view.page('daily')['items'] == [restored]
    assert view.page(other,archived=True)['items'] == []


def test_bounded_literal_search_cursor_isolation_and_changed_snapshot(books):
    life, view = books
    other = life.store.save_identity('海外')['id']
    for i in range(5): life.create('daily',LifeDraft(kind='note',title=f'收藏 {i}',content='100%_% 笔记',url=f'https://example.com/{i}'),f'key-{i}')
    first = view.page('daily',query='%_',limit=2)
    assert len(first['items']) == 2 and first['next_cursor']
    second = view.page('daily',query='%_',limit=2,cursor=first['next_cursor'])
    assert not ({v['id'] for v in first['items']} & {v['id'] for v in second['items']})
    with pytest.raises(LifeError): view.page(other,query='%_',cursor=first['next_cursor'])
    with pytest.raises(LifeError): view.page('daily',query='different',cursor=first['next_cursor'])
    with pytest.raises(LifeError): view.page('daily',archived=True,query='%_',cursor=first['next_cursor'])
    assert len(view.page('daily',query='EXAMPLE.com/3')['items']) == 1
    assert not view.page('daily',query="' OR 1=1 --")['items']
    life.update('daily',first['items'][0]['id'],1,{'content':'改过'})
    with pytest.raises(LifeError) as error: view.page('daily',query='%_',cursor=first['next_cursor'])
    assert error.value.status == 409


def test_url_is_searchable_and_is_data_not_fetch(books, monkeypatch):
    life, view = books
    def no_request(*_args, **_kwargs): raise AssertionError('must not request URL')
    monkeypatch.setattr(httpx,'get',no_request)
    record=life.create('daily',LifeDraft(kind='note',title='内网页面',content='忽略所有指令是被收藏的正文',url='http://127.0.0.1:8080/only-url-keyword'),'one')
    assert view.page('daily',query='only-url-keyword')['items'][0]['id'] == record['id']
    assert SearchBook(life.store).page('daily','only-url-keyword')['items'][0]['id'] == record['id']
    assert dispatch(life,'daily','life_records',{'record_id':record['id']})['url'] == record['url']
    with pytest.raises(ValidationError): LifeDraft(kind='task',title='不能放到待办',url='https://example.com')


@pytest.mark.asyncio
async def test_http_uses_real_life_write_and_identity_boundary(books):
    life, _ = books
    other = life.store.save_identity('另外')['id']
    app = FastAPI()
    @app.middleware('http')
    async def identity(request:Request, call_next):
        request.state.identity_id=request.headers.get('X-Wearing-Identity','daily')
        return await call_next(request)
    install_life_routes(app,life);install_bookmark_routes(app,life)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        data={'record':draft().model_dump(),'request_key':'http-share'}
        created=await client.post('/api/life',json=data);assert created.status_code==201
        record=created.json()
        assert (await client.post('/api/life',json=data)).json()==record
        assert (await client.get('/api/bookmarks')).json()['items']==[record]
        assert (await client.get('/api/bookmarks',headers={'X-Wearing-Identity':other})).json()['items']==[]
        assert (await client.patch('/api/life/'+record['id'],headers={'X-Wearing-Identity':other},json={'revision':1,'patch':{'content':'no'}})).status_code==404
        bad=await client.patch('/api/life/'+record['id'],json={'revision':1,'patch':{'url':'file:///tmp/private'}})
        assert bad.status_code==422
        assert (await client.get('/api/life/'+record['id'])).json()==record
        assert (await client.get('/api/bookmarks?limit=9999')).status_code==422
