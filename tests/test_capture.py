from concurrent.futures import ThreadPoolExecutor
import asyncio
import io
import json
import os
import sqlite3

import httpx
from PIL import Image
import pytest

from wearing.app import create_app
from wearing.capture import CaptureBook, CaptureDraft, OrganizedNote
from wearing.capture_worker import CaptureWorker
from wearing.config import Settings
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.store import Store


def png():
    out=io.BytesIO();Image.new('RGB',(20,20),'white').save(out,format='PNG');return out.getvalue()


@pytest.fixture
def book(tmp_path):return CaptureBook(LifeBook(Store(tmp_path/'wearing.sqlite3')))


def asset(book,key='image-one'):return book.upload('daily',png(),'海报.png','image/png',key)


def capture(book,asset_id=None,key='capture-one'):
    return book.create('daily',CaptureDraft(record=LifeDraft(kind='note',title='先收藏',content='周末想去，先收藏。'),asset_ids=[asset_id] if asset_id else [],request_key=key))


def test_original_exact_private_and_scoped(book):
    a=asset(book);path,row=book.file('daily',a['id'])
    assert path.read_bytes()==png() and row['mime']=='image/png'
    if os.name!='nt':assert path.stat().st_mode&0o777==0o600
    other=book.store.save_identity('海外')['id']
    with pytest.raises(LifeError):book.file(other,a['id'])
    with pytest.raises(LifeError):book.file('daily','../../config.yaml')
    path.unlink();path.symlink_to(book.store.path)
    with pytest.raises(LifeError):book.file('daily',a['id'])


def test_concurrent_upload_retries_write_one_original(book):
    with ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(lambda _:asset(book),range(4)))
    assert len({value['id'] for value in values})==1
    assert len(list(book.root.iterdir()))==1
    with pytest.raises(LifeError):book.upload('daily',png(),'different.png','image/png','image-one')


@pytest.mark.parametrize('data,mime',[(b'<svg>bad</svg>','image/svg+xml'),(b'not png','image/png'),(b'not audio','audio/webm'),(b'','image/png')])
def test_bad_media_rejected_before_any_save(book,data,mime):
    with pytest.raises(LifeError):book.upload('daily',data,'../data',mime,'bad')
    assert not list(book.root.iterdir())


def test_capture_atomic_and_idempotent_with_scope(book):
    a=asset(book)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(lambda _:capture(book,a['id']),range(4)))
    assert len({job['id'] for job in values})==1
    item=book.life.get('daily',values[0]['record_id'])
    assert item['capture']['assets'][0]['id']==a['id']
    assert item['capture']['original_text']=='周末想去，先收藏。'
    assert len(book.life.snapshot('daily')['items'])==1
    other=book.store.save_identity('海外')['id']
    draft=CaptureDraft(record=LifeDraft(kind='note',title='另一身份'),asset_ids=[a['id']],request_key='other')
    with pytest.raises(LifeError):book.create(other,draft)
    with book.store.connection() as db:
        db.execute("CREATE TRIGGER fixture_capture_failure BEFORE INSERT ON life_captures BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):capture(book,key='failed-save')
    assert len(book.life.snapshot('daily')['items'])==1


def test_job_states_bump_feed_without_record_revision(book):
    job=capture(book);before=book.life.snapshot('daily')['version'];claimed=book.claim()
    assert claimed['id']==job['id'] and book.claim() is None
    snapshot=book.life.snapshot('daily',before)
    assert snapshot['items'][0]['capture']['state']=='extracting'
    assert snapshot['items'][0]['revision']==1
    book.recover();assert book.get('daily',job['id'])['state']=='paused'
    assert book.claim() is None
    retry=book.retry('daily',job['id']);assert retry['generation']==2
    assert book.retry('daily',job['id'])['generation']==2
    book.claim();book.state(retry,'failed',error='模型不可用')
    third=book.retry('daily',job['id']);book.claim();book.state(third,'failed',error='模型不可用')
    with pytest.raises(LifeError):book.retry('daily',job['id'])


def test_full_organization_queue_does_not_block_plain_original_save(book):
    a=asset(book)
    for i in range(20):capture(book,key=f'queued-{i}')
    with pytest.raises(LifeError) as error:capture(book,key='over-limit')
    assert error.value.status==429
    job=book.create('daily',CaptureDraft(record=LifeDraft(kind='note',title='先保存原件'),asset_ids=[a['id']],request_key='save-only',organize=False))
    assert job['state']=='saved'
    assert book.life.get('daily',job['record_id'])['capture']['assets'][0]['id']==a['id']


def test_late_organization_preserves_manual_edit_and_original(book):
    job=capture(book);book.claim()
    manual=book.life.update('daily',job['record_id'],1,{'content':'我现在决定不去了。'})
    assert not book.apply(job,OrganizedNote(title='计划周末出门',content='原模型晚回来的旧结果'))
    current=book.life.get('daily',job['record_id'])
    assert current['content']==manual['content'] and current['revision']==2
    assert current['capture']['state']=='conflict'
    assert current['capture']['proposal']['content']=='原模型晚回来的旧结果'
    assert current['capture']['original_text']=='周末想去，先收藏。'


def test_archive_not_revived_by_late_result(book):
    job=capture(book);book.claim();book.life.update('daily',job['record_id'],1,action='archive')
    assert not book.apply(job,OrganizedNote(title='新标题',content='不能复活'))
    assert book.life.get('daily',job['record_id'])['deleted_at']
    assert not book.life.snapshot('daily')['items']


def test_generation_and_duplicate_results_are_fenced(book):
    old=capture(book);book.claim();book.state(old,'failed',error='中断')
    current=book.retry('daily',old['id']);book.claim()
    proposal=OrganizedNote(title='公园散步',content='周末散步，顺便看书店。')
    assert not book.apply(old,proposal)
    assert book.apply(current,proposal)
    assert not book.apply(current,proposal)
    record=book.life.get('daily',current['record_id'])
    assert record['revision']==2 and record['capture']['state']=='done'


def test_paused_job_rejects_late_model_result(book):
    job=capture(book);book.claim();book.recover()
    assert not book.apply(job,OrganizedNote(title='迟来的结果',content='不能覆盖已中断的整理。'))
    assert book.life.get('daily',job['record_id'])['revision']==1
    assert book.get('daily',job['id'])['state']=='paused'


@pytest.mark.asyncio
async def test_retry_extracts_missing_attachment_and_reuses_completed_source(book,monkeypatch):
    first=asset(book);second=asset(book,'image-two')
    job=book.create('daily',CaptureDraft(record=LifeDraft(kind='note',title='两份原件'),asset_ids=[first['id'],second['id']],request_key='partial'))
    job=book.claim();worker=CaptureWorker(book);calls=[]
    monkeypatch.setattr(worker,'capabilities',lambda:{'ocr':'apple-vision'})
    async def command(args,**kwargs):
        calls.append(args[-1])
        if len(calls)==2:raise LifeError('第二份暂时读取失败')
        return json.dumps({'text':'已读到的文字'})
    monkeypatch.setattr(worker,'command',command)
    with pytest.raises(LifeError):await worker.extract(job)
    book.state(job,'failed',error='第二份暂时读取失败')
    assert len(book.get('daily',job['id'])['extracted'])==1
    book.retry('daily',job['id']);retry=book.claim()
    parts=await worker.extract(retry)
    assert [part['asset_id'] for part in parts]==[first['id'],second['id']]
    assert len(calls)==3 and calls[1]==calls[2] and calls[0]!=calls[2]


@pytest.mark.asyncio
async def test_upload_api_guards_original_and_persisted_capture(tmp_path):
    app=create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        url='/api/life/assets?name=poster.png&request_key=upload-api'
        assert (await c.post(url,content=png(),headers={'Content-Type':'image/png'})).status_code==403
        c.headers['X-Wearing-Token']=(await c.get('/api/bootstrap')).json()['token']
        assert (await c.post(url,content=png(),headers={'Content-Type':'image/png','Origin':'https://other.example'})).status_code==403
        response=await c.post(url,content=png(),headers={'Content-Type':'image/png'});assert response.status_code==201
        a=response.json(); original=await c.get('/api/life/assets/'+a['id'])
        assert original.content==png() and 'no-store' in original.headers['cache-control']
        draft={'record':{'kind':'note','title':'先收藏','content':'这是示例'},'asset_ids':[a['id']],'request_key':'save-api'}
        response=await c.post('/api/captures',json=draft);assert response.status_code==201
        item=response.json()['record'];assert item['capture']['state']=='queued'
        other=(await c.post('/api/identities',json={'name':'海外','description':'','region':'international'})).json()['id']
        c.headers['X-Wearing-Identity']=other
        assert (await c.get('/api/life/assets/'+a['id'])).status_code==404
        assert (await c.post('/api/captures',json=draft)).status_code==404
        assert (await c.post('/api/captures/'+item['capture']['id']+'/retry',json={})).status_code==404


@pytest.mark.asyncio
async def test_worker_completed_output_is_validated_and_original_already_saved(book,monkeypatch):
    job=capture(book);book.claim();worker=CaptureWorker(book)
    async def extract(_):return [{'kind':'transcript','asset_id':'fixture','text':'周末去公园散步，先记下来。'}]
    async def command(*args,**kwargs):
        assert book.life.get('daily',job['record_id'])['capture']['state']=='organizing'
        return json.dumps({'output':json.dumps({'title':'周末散步','content':'先记下去公园散步的念头。'},ensure_ascii=False)},ensure_ascii=False)
    monkeypatch.setattr(worker,'extract',extract);monkeypatch.setattr(worker,'command',command)
    from wearing.runtime import HermesRuntime
    monkeypatch.setattr(HermesRuntime,'python',property(lambda _:book.store.path))
    await worker.run(job)
    record=book.life.get('daily',job['record_id'])
    assert record['capture']['state']=='done' and record['title']=='周末散步'
    assert record['capture']['original_text']=='周末想去，先收藏。'


@pytest.mark.asyncio
async def test_worker_invalid_output_does_not_mutate_record(book,monkeypatch):
    job=capture(book);book.claim();worker=CaptureWorker(book)
    async def extract(_):return []
    async def command(*args,**kwargs):return json.dumps({'output':'{"title":"x","content":"x","completed":true}'})
    monkeypatch.setattr(worker,'extract',extract);monkeypatch.setattr(worker,'command',command)
    from wearing.runtime import HermesRuntime
    monkeypatch.setattr(HermesRuntime,'python',property(lambda _:book.store.path))
    await worker.run(job)
    record=book.life.get('daily',job['record_id'])
    assert record['capture']['state']=='failed' and record['revision']==1


@pytest.mark.asyncio
async def test_cancel_and_single_worker_lock(book,monkeypatch):
    job=capture(book);first=CaptureWorker(book);second=CaptureWorker(book)
    first.start();second.start();assert first.owns_lock and not second.owns_lock
    started=asyncio.Event()
    async def extraction(_):started.set();await asyncio.Event().wait()
    monkeypatch.setattr(first,'extract',extraction)
    first.tick();await started.wait();await first.close()
    assert book.get('daily',job['id'])['state']=='paused'
    second.start();assert second.owns_lock and book.claim() is None
    await second.close()
