import copy
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError
from wearing.store import Store
from wearing.calendar_series import CalendarSeriesBook, SeriesError
from wearing.calendar_series_api import execute, install_calendar_series_routes


@pytest.fixture
def book(tmp_path): return CalendarSeriesBook(Store(tmp_path/'series.sqlite3'))


def draft(**patch):
    return {'template':{'title':'合成每周安排','content':'仅测试','timezone':'Asia/Shanghai','all_day':False,'start_local':'2026-10-08T09:00','end_local':'2026-10-08T10:00'},'rule':{'frequency':'weekly'},**patch}


def create(book,value=None,key='create'): return book.mutate('daily',key,'create',draft=value or draft())
def query(book,start='2026-10-01',end='2026-11-01',**kwargs):return book.query('daily',start,end,**kwargs)


def test_series_rule_is_canonical_not_a_pile_of_life_copies(book):
    first=create(book)
    rows=query(book)['items']
    assert len(rows)==4 and rows[0]['start_at']=='2026-10-08T01:00:00+00:00'
    assert len({r['id'] for r in rows})==4
    assert {r['recurrence']['series_id'] for r in rows}=={first['id']}
    with book.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM calendar_series').fetchone()[0]==1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='life_records'").fetchone()


def test_count_until_weekdays_and_interval(book):
    value=draft(rule={'frequency':'weekly','interval':2,'weekdays':[0,3],'count':3})
    create(book,value)
    assert [r['recurrence']['occurrence_key'] for r in query(book)['items']]==['2026-10-08','2026-10-19','2026-10-22']
    other=draft(rule={'frequency':'daily','until':'2026-10-10'})
    second=create(book,other,'second')
    assert len(query(book,series_id=second['id'])['items'])==3


def test_month_end_leap_day_and_invalid_dates_do_not_consume_count(book):
    value=draft(rule={'frequency':'monthly','count':3});value['template'].update(start_local='2026-01-31T09:00',end_local='2026-01-31T10:00')
    row=create(book,value)
    assert [r['recurrence']['occurrence_key'] for r in query(book,'2026-01-01','2027-01-01',series_id=row['id'])['items']]==['2026-01-31','2026-03-31','2026-05-31']
    value=draft(rule={'frequency':'yearly','count':2});value['template'].update(start_local='2024-02-29T09:00',end_local='2024-02-29T10:00')
    second=create(book,value,'leap')
    assert query(book,'2025-01-01','2026-01-01',series_id=second['id'])['items']==[]
    assert len(query(book,'2028-01-01','2029-01-01',series_id=second['id'])['items'])==1


def test_dst_skipped_nonexistent_times_keep_local_clock_and_ambiguous_time_uses_first_fold(book):
    value=draft(rule={'frequency':'daily','count':3});value['template'].update(timezone='America/New_York',start_local='2026-03-07T02:30',end_local='2026-03-07T03:30')
    create(book,value)
    rows=query(book,'2026-03-07','2026-03-12',timezone='America/New_York')['items']
    assert [r['recurrence']['occurrence_key'] for r in rows]==['2026-03-07','2026-03-09','2026-03-10']
    assert rows[1]['start_at']=='2026-03-09T06:30:00+00:00'
    value=draft(rule={'frequency':'daily','count':1});value['template'].update(timezone='America/New_York',start_local='2026-11-01T01:30',end_local='2026-11-01T02:30')
    second=create(book,value,'fold')
    assert query(book,'2026-11-01','2026-11-02',series_id=second['id'],timezone='America/New_York')['items'][0]['start_at']=='2026-11-01T05:30:00+00:00'


def test_query_uses_requested_display_timezone_and_midnight_end_is_excluded(book):
    value=draft(rule={'frequency':'daily','count':1});value['template'].update(start_local='2026-10-08T00:30',end_local='2026-10-08T01:00')
    create(book,value)
    assert len(query(book,'2026-10-07','2026-10-08',timezone='America/New_York')['items'])==1
    assert query(book,'2026-10-08','2026-10-09',timezone='America/New_York')['items']==[]
    value['template'].update(start_local='2026-10-08T23:00',end_local='2026-10-09T00:00')
    second=create(book,value,'midnight')
    assert query(book,'2026-10-09','2026-10-10',series_id=second['id'])['items']==[]


def test_all_day_keeps_civil_dates_and_multiday_overlap(book):
    value=draft(rule={'frequency':'weekly','count':1});value['template'].update(all_day=True,start_local='2026-10-08',end_local='2026-10-11')
    row=create(book,value)
    for zone in ['Asia/Shanghai','Pacific/Honolulu']:
        found=query(book,'2026-10-10','2026-10-11',timezone=zone)['items'];assert len(found)==1 and found[0]['start_at']=='2026-10-08'
    assert query(book,'2026-10-11','2026-10-12',series_id=row['id'])['items']==[]


def test_occurrence_move_cancel_reset_and_stable_id(book):
    row=create(book);original=query(book)['items'][0]
    template={**row['body']['template'],'title':'这一次改到下个月','start_local':'2026-12-12T11:00','end_local':'2026-12-12T12:00'}
    changed=book.mutate('daily','once','override',row['id'],1,occurrence_key='2026-10-08',template=template)
    assert len(query(book)['items'])==3
    moved=query(book,'2026-12-12','2026-12-13')['items'][0];assert moved['id']==original['id'] and moved['title']==template['title']
    book.mutate('daily','cancel','cancel',row['id'],changed['revision'],occurrence_key='2026-10-08')
    assert query(book,'2026-12-12','2026-12-13')['items']==[]
    book.mutate('daily','restore-once','reset',row['id'],3,occurrence_key='2026-10-08')
    assert query(book)['items'][0]['id']==original['id']


def test_selected_occurrence_reads_latest_exception_and_cancel_state(book):
    row=create(book)
    template={**row['body']['template'],'title':'新的实例内容'}
    book.mutate('daily','edit','override',row['id'],1,occurrence_key='2026-10-08',template=template)
    selected=book.get('daily',row['id'],'2026-10-08')
    assert selected['revision']==selected['selected']['revision']==2
    assert selected['selected']['title']=='新的实例内容'
    book.mutate('daily','cancel','cancel',row['id'],2,occurrence_key='2026-10-08')
    assert book.get('daily',row['id'],'2026-10-08')['selected'] is None
    assert book.get('daily',row['id'],'2026-10-09')['selected'] is None


def test_series_edit_preserves_exceptions_and_rejects_orphan_rules(book):
    row=create(book)
    book.mutate('daily','one','override',row['id'],1,occurrence_key='2026-10-08',template={**row['body']['template'],'title':'保留例外'})
    value=copy.deepcopy(row['body']);value['template']['title']='修改整个系列'
    book.mutate('daily','all','update',row['id'],2,draft=value)
    rows=query(book)['items'];assert rows[0]['title']=='保留例外' and rows[1]['title']=='修改整个系列'
    value['template'].update(start_local='2026-10-09T09:00',end_local='2026-10-09T10:00')
    with pytest.raises(SeriesError,match='遗漏已有例外'):book.mutate('daily','orphan','update',row['id'],3,draft=value)
    assert book.get('daily',row['id'])['revision']==3


def test_cas_lost_receipt_replay_and_parallel_create_are_atomic(book):
    with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(lambda _:create(book),range(4)))
    assert rows.count(rows[0])==4
    row=rows[0];book.mutate('daily','archive','archive',row['id'],1)
    with pytest.raises(SeriesError):book.mutate('daily','stale','update',row['id'],1,draft=draft())
    replay=CalendarSeriesBook(Store(book.store.path)).mutate('daily','archive','archive',row['id'],1)
    assert replay['revision']==2 and replay['deleted_at']
    with pytest.raises(SeriesError):book.mutate('daily','archive','restore',row['id'],2)
    assert query(book)['items']==[]
    assert book.list('daily',include_deleted=True)['items'][0]['id']==row['id']


def test_range_and_results_are_bounded_with_explicit_truncation(book):
    for n in range(4):create(book,draft(rule={'frequency':'daily'}),str(n))
    result=query(book,'2026-10-01','2027-10-01')
    assert result['truncated'] and result['limit']==1000 and len(result['items'])==1000
    with pytest.raises(SeriesError):query(book,'2026-01-01','2028-01-01')


@pytest.mark.parametrize('patch',[
    {'rule':{'frequency':'weekly','weekdays':[True]}},
    {'rule':{'frequency':'daily','count':True}},
    {'rule':{'frequency':'daily','count':2,'until':'2026-10-11'}},
    {'rule':{'frequency':'monthly','weekdays':[1]}},
    {'template':{'title':'bad','start_local':'2026-03-08T02:30','end_local':'2026-03-08T03:30','timezone':'America/New_York'}},
])
def test_invalid_rules_and_times_cannot_write(book,patch):
    with pytest.raises((ValueError,ValidationError)):create(book,draft(**patch))
    assert book.list('daily')['items']==[]


@pytest.mark.asyncio
async def test_http_identity_cannot_be_forged_and_command_fields_are_exact(book):
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,call_next):request.state.identity_id='daily';return await call_next(request)
    install_calendar_series_routes(app,book)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        body={'action':'create','request_key':'new','draft':draft()}
        assert (await client.post('/api/calendar-series',json={**body,'identity':'other'})).status_code==422
        result=(await client.post('/api/calendar-series',json=body)).json();assert result['identity_id']=='daily'
        assert (await client.post('/api/calendar-series',json={'action':'archive','series_id':result['id'],'revision':1,'request_key':'wrong','template':draft()['template']})).status_code==422
        assert (await client.post('/api/calendar-series',json={'action':'query','start':'2026-10-01','end':'2026-11-01','timezone':'Invalid/Zone'})).status_code==422
        other = book.store.save_identity('测试另一身份')
        with pytest.raises(SeriesError):book.get(other['id'],result['id'])


def test_agent_command_uses_identical_series_and_occurrence_contract(book):
    from wearing.calendar_series_tools import dispatch
    row=dispatch(book.store,'daily','calendar_series',{'action':'create','request_key':'agent','draft':draft()})
    result=execute(book,'daily',{'action':'query','start':'2026-10-01','end':'2026-11-01','timezone':'Asia/Shanghai','series_id':row['id']})
    assert len(result['items'])==4
