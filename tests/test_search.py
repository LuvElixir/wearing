import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from wearing.life import LifeBook, LifeDraft
from wearing.search import SearchBook, SearchError
from wearing.search_api import install_search_routes
from wearing.store import Store


@pytest.fixture
def corpus(tmp_path):
    store = Store(tmp_path/'wearing.sqlite3')
    life = LifeBook(store)
    other = store.save_identity('工作')['id']
    task = store.create('查一下台北旅行', '研究')
    store.update(task['id'], output='可以在下午去博物馆。', payload={'secret':'never-index-canary'}, error='private-error-canary')
    chat = store.create_message('帮我安排台北住宿')
    store.update(chat['id'], output='旅行选择：大稻埕，夜晚散步。')
    note = life.create('daily', LifeDraft(kind='note',title='旅行清单',content='台北交通卡和雨伞'), 'qa-record')
    deleted = life.create('daily', LifeDraft(kind='note',title='删除专用词'), 'qa-deleted')
    life.update('daily',deleted['id'],1,action='archive')
    secret = store.create_message('隔离旅行秘密', other)
    return store, life, SearchBook(store), task, chat, note, other, secret


def test_search_full_text_snippets_types_and_exact_safe_targets(corpus):
    store, life, book, task, chat, note, other, secret = corpus
    page=book.page('daily','旅行')
    assert {i['kind'] for i in page['items']} == {'task','record','message'}
    assert page['files_included'] is False
    assert all('旅行' in i['snippet'] for i in page['items'])
    assert {tuple(sorted(i['target'])) for i in page['items']} == {('kind','task_id'),('kind','record_id'),('kind','message_id','task_id')}
    assert all(secret['id'] != i['target'].get('task_id') for i in page['items'])
    # A conversation turn appears once in all; the explicit task filter still
    # searches all real execution tasks, including those created from messages.
    assert len([i for i in page['items'] if i['target'].get('task_id') == chat['id']]) == 1
    assert {i['id'] for i in book.page('daily','旅行',kind='task')['items']} == {task['id'],chat['id']}
    for keyword in ['never-index-canary','private-error-canary','删除专用词','隔离旅行秘密']:
        assert book.page('daily',keyword)['items'] == []


def test_server_pages_reach_old_matches_beyond_200_and_ties_are_stable(corpus):
    store, life, book, *_ = corpus
    with store.connection() as db:
        db.executemany('INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,?,?,?,?,?,?)',
            [(f'qa_{i:04}','批量关键字',f'正文 {i}','研究','draft',f'session{i}','2020-01-01T00:00:00+00:00','2020-01-01T00:00:00+00:00','daily') for i in range(257)])
    first=book.page('daily','批量关键字',limit=17)
    second=book.page('daily','批量关键字',limit=17,cursor=first['next_cursor'])
    assert book.page('daily','批量关键字',limit=17,cursor=first['next_cursor']) == second
    seen=[]; page=first
    while True:
        assert len(page['items']) <= 17
        seen.extend(i['id'] for i in page['items'])
        if not page['next_cursor']:break
        page=book.page('daily','批量关键字',limit=17,cursor=page['next_cursor'])
    assert len(seen)==len(set(seen))==257 and 'qa_0256' in seen


def test_cursor_bound_to_identity_query_type_signature_expiry_and_restart(corpus):
    store, life, book, task, chat, note, other, secret=corpus
    cursor=book.page('daily','旅行',limit=1)['next_cursor']
    for identity,q,kind,token in [(other,'旅行','all',cursor),('daily','台北','all',cursor),('daily','旅行','record',cursor),('daily','旅行','all',cursor[:-1]+'x')]:
        with pytest.raises(SearchError) as issue:book.page(identity,q,kind=kind,cursor=token)
        assert issue.value.status==409
    with pytest.raises(SearchError):SearchBook(store).page('daily','旅行',cursor=cursor)
    book.clock=lambda:10**12
    with pytest.raises(SearchError):book.page('daily','旅行',cursor=cursor)


def test_new_edits_and_insertions_wait_for_refresh_without_duplicate_results(corpus):
    store, life, book, task, chat, note, other, secret=corpus
    first=book.page('daily','旅行',limit=1)
    store.update(task['id'],output='旅行新结果')
    new=store.create('旅行刚加入','研究')
    pages=[first]; cursor=first['next_cursor']
    while cursor:
        page=book.page('daily','旅行',limit=1,cursor=cursor);pages.append(page);cursor=page['next_cursor']
    keys=[i['key'] for p in pages for i in p['items']]
    assert len(keys)==len(set(keys)) and 'task:'+new['id'] not in keys
    assert 'task:'+new['id'] in [i['key'] for i in book.page('daily','旅行')['items']]


def test_literal_punctuation_and_case_insensitivity(corpus):
    store,life,book,*_=corpus
    store.create('Budget 50% [draft] A_B + C++','研究')
    for q in ['50%','[draft]','A_B','c++','budget']:
        assert len(book.page('daily',q)['items'])==1
    assert book.page('daily',"' OR 1=1 --")['items']==[]
    for q in ['', '  ', 'a'*121, 'x\x00']:
        with pytest.raises(SearchError):book.page('daily',q)
    with pytest.raises(SearchError):book.page('daily','旅行',limit=51)


def test_precise_message_reads_never_cross_identity_or_return_internal_fields(corpus):
    store,life,book,task,chat,note,other,secret=corpus
    hit=book.page('daily','大稻埕')['items'][0]
    message=book.message('daily',hit['target']['message_id'])
    assert message['task_id']==chat['id'] and message['content']=='帮我安排台北住宿'
    assert '大稻埕' in message['output']
    assert not {'payload','session_id','run_id','idempotency_key'} & set(message)
    with pytest.raises(SearchError) as issue:book.message(other,message['id'])
    assert issue.value.status==404


def test_query_budget_fails_visibly_instead_of_returning_false_empty(corpus):
    store,life,_,*_ = corpus
    with store.connection() as db:
        db.executemany('INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,?,?,?,?,?,?)',
            [(f'time_{i}','haystack','not here','研究','draft',f's{i}','2020','2020','daily') for i in range(1000)])
    with pytest.raises(SearchError) as issue:SearchBook(store,budget=-1).page('daily','needle')
    assert issue.value.status==503


async def test_http_boundary_identity_cursor_and_detail_contract(corpus):
    store,life,book,task,chat,note,other,secret=corpus
    app=FastAPI()
    @app.middleware('http')
    async def boundary(request: Request,next):
        if request.headers.get('authorization') != 'Bearer qa-only':return JSONResponse({},status_code=401)
        request.state.identity_id=request.headers.get('x-wearing-identity','daily')
        return await next(request)
    install_search_routes(app,book)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://testserver') as client:
        assert (await client.get('/api/search?q=旅行')).status_code==401
        headers={'authorization':'Bearer qa-only','x-wearing-identity':'daily'}
        first=await client.get('/api/search',params={'q':'旅行','limit':1,'identity':other},headers=headers)
        assert first.status_code==200 and first.json()['identity_id']=='daily'
        assert (await client.get('/api/search',params={'q':'旅行','cursor':first.json()['next_cursor']},headers={**headers,'x-wearing-identity':other})).status_code==409
        hit=book.page('daily','大稻埕')['items'][0]
        path=f"/api/search/messages/{hit['target']['message_id']}"
        assert (await client.get(path,headers=headers)).status_code==200
        assert (await client.get(path,headers={**headers,'x-wearing-identity':other})).status_code==404
        assert (await client.get('/api/search?q=test&limit=100',headers=headers)).status_code==422
