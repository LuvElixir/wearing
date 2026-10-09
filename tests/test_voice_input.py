"""Voice is scoped input, not an inferred note or a command."""
import asyncio
import io
import json
import wave
import sys
from pathlib import Path
import httpx
import pytest
from wearing.app import create_app
from wearing.capture import CaptureBook
from wearing.capture_worker import CaptureWorker
from wearing.config import Settings
from wearing.life import LifeBook, LifeError
from wearing.store import Store


def wav():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes(b'\x00\x00' * 1600)
    return stream.getvalue()


@pytest.fixture
def voice(tmp_path, monkeypatch):
    book = CaptureBook(LifeBook(Store(tmp_path / 'wearing.sqlite3')))
    asset = book.upload('daily', wav(), 'voice.wav', 'audio/wav', 'voice-test')
    worker = CaptureWorker(book)
    monkeypatch.setattr(worker, 'capabilities', lambda: {'transcription': 'test'})
    return book, asset, worker


@pytest.mark.asyncio
async def test_retry_reuses_transcript_without_creating_record(voice, monkeypatch):
    book, asset, worker = voice
    calls = []
    async def command(args, **kwargs):
        calls.append(args)
        assert book.file('daily', asset['id'])[0].is_file()
        return json.dumps({'text': '  明天下午提醒我拿快递。  '})
    monkeypatch.setattr(worker, 'command', command)
    result = await worker.transcribe_voice('daily', asset['id'])
    assert result == {'asset_id': asset['id'], 'text': '明天下午提醒我拿快递。'}
    assert await worker.transcribe_voice('daily', asset['id']) == result
    assert len(calls) == 1 and not worker.voice_busy
    assert book.life.snapshot('daily')['items'] == []
    other = book.store.save_identity('另一身份')['id']
    with pytest.raises(LifeError) as error: await worker.transcribe_voice(other, asset['id'])
    assert error.value.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', ['{}', '{"text":null}', '{"text":"  "}', '{"text":10}', '{"text":"' + 'x'*12001 + '"}', 'invalid json'])
async def test_bad_transcript_keeps_original_and_releases_worker(voice, monkeypatch, raw):
    book, asset, worker = voice
    async def command(*args, **kwargs): return raw
    monkeypatch.setattr(worker, 'command', command)
    with pytest.raises(LifeError): await worker.transcribe_voice('daily', asset['id'])
    assert not worker.voice_busy and book.transcript('daily', asset['id']) is None
    assert book.file('daily', asset['id'])[0].read_bytes() == wav()


@pytest.mark.asyncio
async def test_parallel_requests_do_not_overlap_and_timeout_can_retry(voice, monkeypatch):
    book, asset, worker = voice
    started, release = asyncio.Event(), asyncio.Event()
    async def command(*args, **kwargs):
        started.set(); await release.wait(); raise asyncio.TimeoutError()
    monkeypatch.setattr(worker, 'command', command)
    task = asyncio.create_task(worker.transcribe_voice('daily', asset['id']))
    await started.wait()
    with pytest.raises(LifeError) as error: await worker.transcribe_voice('daily', asset['id'])
    assert error.value.status == 409
    release.set()
    with pytest.raises(LifeError) as error: await task
    assert error.value.status == 503 and not worker.voice_busy
    assert book.file('daily', asset['id'])[0].exists()


@pytest.mark.asyncio
async def test_missing_engine_preserves_audio(voice, monkeypatch):
    book, asset, worker = voice
    monkeypatch.setattr(worker, 'capabilities', lambda: {'transcription': None})
    with pytest.raises(LifeError) as error: await worker.transcribe_voice('daily', asset['id'])
    assert error.value.status == 503 and book.file('daily', asset['id'])[0].exists()


@pytest.mark.parametrize('payload,status', [({'error_code':'duration_limit'},422),({'error_code':'invalid_audio'},422),
                                            ({'error_code':'decoder_unavailable'},503),({'error':'failure'},503)])
async def test_decoder_failure_protocol_preserves_audio_and_never_saves_error_text(voice,monkeypatch,payload,status):
    book,asset,worker=voice
    async def command(*args,**kwargs):return json.dumps(payload)
    monkeypatch.setattr(worker,'command',command)
    with pytest.raises(LifeError) as error:await worker.transcribe_voice('daily',asset['id'])
    assert error.value.status==status and not worker.voice_busy
    assert book.transcript('daily',asset['id']) is None and book.file('daily',asset['id'])[0].exists()


@pytest.mark.parametrize('command', [[sys.executable,'-c','raise SystemExit(1)'],['/nonexistent-wearing-decoder']])
async def test_subprocess_unavailable_is_retryable_and_releases_lease(voice,command):
    _,_,worker=voice
    with pytest.raises(LifeError) as error:await worker.command(command)
    assert error.value.status==503 and worker.process is None and not worker.process_busy
    assert not worker.process_lock.is_locked
    assert (await worker.command([sys.executable,'-c','print("ok")'])).strip()=='ok'


async def test_local_decoder_slot_is_shared_across_workers_and_cancel_releases_it(voice):
    book,_,worker=voice
    other=CaptureWorker(book)
    task=asyncio.create_task(worker.command([sys.executable,'-c','import time; time.sleep(10)']))
    for _ in range(100):
        if worker.process is not None:break
        await asyncio.sleep(.01)
    assert worker.process is not None
    for busy in (worker,other):
        with pytest.raises(LifeError) as error:await busy.command([sys.executable,'-c','print("must-not-run")'])
        assert error.value.status==409
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert not worker.process_busy and not worker.process_lock.is_locked and worker.process is None
    assert (await other.command([sys.executable,'-c','print("released")'])).strip()=='released'


async def test_real_subprocess_timeout_releases_local_decoder_slot(voice):
    book,_,worker=voice
    with pytest.raises(asyncio.TimeoutError):
        await worker.command([sys.executable,'-c','import time; time.sleep(10)'],timeout=.03)
    assert not worker.process_busy and worker.process is None
    other=CaptureWorker(book)
    assert (await other.command([sys.executable,'-c','print("ready")'])).strip()=='ready'


@pytest.mark.parametrize('invalid,code', [(True,'invalid_audio'),(False,'duration_limit')])
async def test_audio_validation_precedes_cloud_upload(voice,tmp_path,invalid,code,monkeypatch):
    from wearing.speech import decode_wav, SpeechError
    source=tmp_path/'decoder-input.wav'
    if invalid:
        source.write_bytes(b'RIFF'+b'\x00'*4+b'WAVE'+b'invalid')
    else:
        with wave.open(str(source),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
            audio.writeframes(b'\x00\x00'*16000*181)
    with pytest.raises(SpeechError) as error: decode_wav(source)
    assert error.value.code == code and source.exists()


@pytest.mark.asyncio
async def test_route_enforces_token_origin_and_identity(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path))
    monkeypatch.setattr(CaptureWorker, 'capabilities', lambda _: {'transcription': 'test'})
    async def command(*args, **kwargs): return json.dumps({'text': '周末出去走走。'})
    monkeypatch.setattr(CaptureWorker, 'command', command)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as c:
        headers = {'X-Wearing-Token': (await c.get('/api/bootstrap')).json()['token']}
        response = await c.post('/api/life/assets?name=voice.wav&request_key=voice-api', content=wav(), headers={**headers, 'Content-Type':'audio/wav'})
        assert response.status_code == 201
        url = '/api/life/assets/' + response.json()['id'] + '/transcribe'
        assert (await c.post(url, json={})).status_code == 403
        assert (await c.post(url, json={}, headers={**headers, 'Origin':'https://other.example'})).status_code == 403
        result = await c.post(url, json={}, headers=headers)
        assert result.status_code == 200 and result.json()['text'] == '周末出去走走。'
        other = (await c.post('/api/identities', json={'name':'其他', 'description':'', 'region':'international'}, headers=headers)).json()['id']
        assert (await c.post(url, json={}, headers={**headers, 'X-Wearing-Identity':other})).status_code == 404
