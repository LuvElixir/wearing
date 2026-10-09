from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from wearing.usage import UsageBook, UsageError, UsagePolicy
from wearing.usage_guard import receipt


def book(tmp_path, **kwargs):
    return UsageBook(tmp_path, enabled=True, **kwargs)


def test_atomic_concurrent_admission_and_global_identity_budget(tmp_path):
    b = book(tmp_path, policy=UsagePolicy(model_calls=3, model_concurrency=2))
    def attempt(i):
        try: return b.reserve('daily' if i % 2 else 'work', 'model', str(i))
        except UsageError as error: return error.code
    with ThreadPoolExecutor(max_workers=10) as pool:
        rows = list(pool.map(attempt, range(10)))
    admitted = [row for row in rows if not row.startswith('quota_')]
    assert len(admitted) == 2
    b.settle(admitted[0], input_tokens=25, output_tokens=7)
    third = b.reserve('new-identity', 'model', 'final')
    b.settle(third)
    with pytest.raises(UsageError, match='额度'):
        b.reserve('brand-new-identity', 'model', 'bypass')
    assert b.snapshot('work')['resources']['model']['calls'] == 3


def test_duplicate_reservation_and_settlement_do_not_charge_twice(tmp_path):
    b = book(tmp_path)
    call = b.reserve('daily', 'model', 'request-1')
    with pytest.raises(UsageError) as error:
        b.reserve('daily', 'model', 'request-1')
    assert error.value.code == 'quota_duplicate'
    b.settle(call, input_tokens=10, output_tokens=2)
    b.settle(call, input_tokens=1000, output_tokens=2000)
    result = b.snapshot('daily')
    assert result['identity_usage']['input_tokens'] == 10
    assert result['resources']['model']['calls'] == 1
    assert result['cost'] is None


def test_restart_keeps_uncertain_charge_and_only_frees_dead_owner_concurrency(tmp_path):
    b = book(tmp_path, policy=UsagePolicy(model_calls=2, model_concurrency=1))
    b.reserve('daily', 'model', 'interrupted')
    restart = book(tmp_path, alive=lambda pid, stamp: False)
    view = restart.snapshot('daily')
    assert view['resources']['model']['uncertain'] == 1
    assert view['resources']['model']['remaining'] == 1
    assert view['identity_usage']['input_tokens'] is None
    assert view['identity_usage']['unreported_model_calls'] == 1
    assert view['cost'] is None
    restart.reserve('daily', 'model', 'new-after-recovery')
    with pytest.raises(UsageError) as error:
        restart.reserve('daily', 'model', 'third')
    assert error.value.code == 'quota_exhausted'


def test_live_owner_is_not_freed_by_restart_or_passage_of_time(tmp_path):
    b = book(tmp_path, policy=UsagePolicy(model_concurrency=1))
    b.reserve('daily', 'model', 'active')
    with sqlite3.connect(b.path) as db:
        db.execute('UPDATE trial_calls SET created_at=0')
    with pytest.raises(UsageError) as error:
        book(tmp_path).reserve('daily', 'model', 'second')
    assert error.value.code == 'quota_busy'


def test_speech_reserves_time_releases_only_unused_time_on_known_completion(tmp_path):
    b = book(tmp_path, policy=UsagePolicy(speech_ms=180_000))
    a = b.reserve('daily', 'speech', 'one', reserve_ms=180_000)
    with pytest.raises(UsageError):
        b.reserve('daily', 'speech', 'two', reserve_ms=1)
    b.settle(a, measured_ms=10_000)
    c = b.reserve('daily', 'speech', 'three', reserve_ms=170_000)
    b.settle(c, uncertain=True)
    view = b.snapshot('daily')['resources']['speech']
    assert view['audio_ms'] == 180_000
    assert view['ms_remaining'] == 0
    assert view['calls'] == 2


def test_default_local_mode_is_not_restricted_and_unknown_not_zero(tmp_path, monkeypatch):
    monkeypatch.delenv('PAJIO_TRIAL_LIMITS', raising=False)
    b = UsageBook(tmp_path, UsagePolicy(model_calls=0))
    b.check()
    assert b.snapshot('daily')['mode'] == 'not_enabled'
    assert b.snapshot('daily')['identity_usage']['input_tokens'] is None
    assert receipt({'usage': {'prompt_tokens': None, 'completion_tokens': False}}) == {}
    assert receipt({'usage': {'prompt_tokens': 0, 'completion_tokens': 5}}) == {'input_tokens': 0, 'output_tokens': 5}


@pytest.mark.asyncio
async def test_speech_guard_stops_before_provider_and_preserves_cancel_charge(tmp_path, monkeypatch):
    from wearing.usage_speech import guarded_recognition
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    b = book(tmp_path, policy=UsagePolicy(speech_calls=1, speech_ms=180_000))
    seen = []
    async def chunks(): yield b'\0\0' * 160
    async def recognize(chunks, key):
        seen.append('network')
        async for _ in chunks: pass
        raise __import__('asyncio').CancelledError()
    with pytest.raises(__import__('asyncio').CancelledError):
        await guarded_recognition(chunks(), 'fake', data_dir=tmp_path, identity='daily', request_key='one', recognize=recognize)
    from wearing.speech import SpeechError
    with pytest.raises(SpeechError) as error:
        await guarded_recognition(chunks(), 'fake', data_dir=tmp_path, identity='daily', request_key='two', recognize=recognize)
    assert error.value.code == 'quota_exhausted'
    assert seen == ['network']
    view = b.snapshot('daily')['resources']['speech']
    assert view['uncertain'] == 1 and view['ms_remaining'] == 0
