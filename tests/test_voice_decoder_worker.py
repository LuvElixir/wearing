"""Cloud ASR envelope, terminal-result handling and private failure boundaries."""
import asyncio
import gzip
import io
import json
import logging
import struct
import wave
from contextlib import asynccontextmanager

import pytest

from wearing.capture import CaptureBook
from wearing.capture_setup import prepare, save_key, speech_key
from wearing.capture_worker import CaptureWorker
from wearing.life import LifeBook
from wearing.speech import (SpeechError, decode_wav, recognize_pcm, request_packet,
                            response_packet, transcribe_file, STREAM_RESOURCE, STREAM_URL)
from wearing.store import Store


def reply(body, final=False):
    payload = gzip.compress(json.dumps(body).encode())
    return bytes((0x11, 0x93 if final else 0x91, 0x11, 0)) + struct.pack('>iI', -1 if final else 1, len(payload)) + payload


def source(tmp_path, rate=44100, channels=2, seconds=.1):
    path = tmp_path/'voice.wav'
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(channels);out.setsampwidth(2);out.setframerate(rate)
        out.writeframes(b'\x01\x00' * int(rate*seconds)*channels)
    return path


def test_pcm_resampling_is_bounded_and_keeps_original(tmp_path):
    path = source(tmp_path)
    original = path.read_bytes()
    audio, duration = decode_wav(path)
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) == (16000, 1, 2, 1600)
    assert duration == .1 and path.read_bytes() == original


def test_config_is_private_and_status_never_contains_key(tmp_path, monkeypatch):
    monkeypatch.delenv('WEARING_SPEECH_API_KEY', raising=False)
    key = 'private-speech-key-do-not-log'
    save_key(tmp_path, key)
    assert speech_key(tmp_path) == key
    assert (tmp_path/'speech.json').stat().st_mode & 0o777 == 0o600
    assert prepare(tmp_path)['prepared']
    assert key not in json.dumps(prepare(tmp_path))
    assert not (tmp_path/'runtime').exists()
    monkeypatch.setenv('WEARING_SPEECH_API_KEY','bad\nkey')
    assert speech_key(tmp_path) == ''


def test_request_audio_envelope_and_final_marker():
    packet = request_packet(b'pcm-bytes', 6, audio=True, final=True)
    assert packet[:4] == bytes((0x11,0x23,0x11,0))
    sequence,length = struct.unpack_from('>iI', packet, 4)
    assert sequence == -6 and length == len(packet)-12
    assert gzip.decompress(packet[12:]) == b'pcm-bytes'


@pytest.mark.parametrize('message', [b'', b'12345678', reply({})[:-1], 'wrong frame',
    reply([]), reply({'code':55000031}), bytes((0x11,0x91,0x11,0))+b'\x00'*8])
def test_invalid_protocol_fails_closed(message):
    with pytest.raises(SpeechError):response_packet(message)


def test_response_decompression_has_a_limit():
    with pytest.raises(SpeechError):response_packet(reply({'result': {'text': 'x'*(1024*1024)}}))


class Socket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False
    async def send(self, packet):
        self.sent.append(packet)
    async def recv(self):
        await asyncio.sleep(0)
        if not self.responses:await asyncio.Event().wait()
        return self.responses.pop(0)


def transport(socket):
    @asynccontextmanager
    async def connect(url, **options):
        assert url == STREAM_URL and options['proxy'] is None
        assert options['additional_headers']['X-Api-Resource-Id'] == STREAM_RESOURCE
        assert options['additional_headers']['X-Api-Key'] == 'test-key'
        try:yield socket
        finally:socket.closed = True
    return connect


async def test_partial_text_is_replaced_and_only_final_is_returned():
    socket = Socket([reply({}), reply({'result': {'text':'明天下午三点'}}),
                     reply({'result': {'text':'明天下午四点拿快递。'}}, True)])
    text = await recognize_pcm(b'\x00\x00'*16000, 'test-key', connect_factory=transport(socket))
    assert text == '明天下午四点拿快递。' and socket.closed
    init = json.loads(gzip.decompress(socket.sent[0][12:]))
    assert init['request']['enable_ddc'] is False
    assert init['request']['enable_itn'] is True
    assert socket.sent[-1][1] == 0x23
    assert gzip.decompress(socket.sent[-1][12:]) == b''
    assert b''.join(gzip.decompress(packet[12:]) for packet in socket.sent[1:]) == b'\x00\x00'*16000


async def test_silence_and_provider_errors_cannot_become_user_text():
    for final in ({'result': {'text':''}}, {'code': 55000031, 'message': 'private detail'}):
        socket = Socket([reply({}), reply(final, True)])
        with pytest.raises(SpeechError) as error:
            await recognize_pcm(b'00', 'test-key', connect_factory=transport(socket))
        assert 'private detail' not in str(error.value) and socket.closed


async def test_cancel_closes_session_without_retry_or_late_transcript():
    socket = Socket([reply({}), reply({'result': {'text':'partial'}})])
    task = asyncio.create_task(recognize_pcm(b'00', 'test-key', connect_factory=transport(socket)))
    for _ in range(100):
        if len(socket.sent) == 2:break
        await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert socket.closed


async def test_no_network_without_configured_key(tmp_path,monkeypatch):
    monkeypatch.delenv('WEARING_SPEECH_API_KEY', raising=False)
    with pytest.raises(SpeechError) as error:await transcribe_file(source(tmp_path), tmp_path)
    assert error.value.code == 'not_configured'


async def test_worker_timing_logs_exclude_transcript_path_and_unexpected_fields(tmp_path,monkeypatch,caplog):
    worker = CaptureWorker(CaptureBook(LifeBook(Store(tmp_path/'wearing.sqlite3'))))
    caplog.set_level(logging.INFO,logger='wearing.capture_worker')
    async def command(args, **kwargs):
        assert '-m' in args and 'wearing.capture_stt' in args and '--serve' not in args
        return json.dumps({'text':'private-text', 'timings': {'decode_ms':2, 'private':'private-detail'}})
    monkeypatch.setattr(worker,'command',command)
    await worker.recognize(tmp_path/'private-audio.wav')
    assert 'private' not in caplog.text and 'worker_ms' in caplog.text


async def test_send_failure_does_not_wait_for_a_receiver_that_will_never_finish():
    socket = Socket([reply({})])
    original = socket.send
    async def fail_audio(packet):
        if packet[1] >> 4 == 2:
            raise OSError('transport failed with private detail')
        await original(packet)
    socket.send = fail_audio
    with pytest.raises(SpeechError) as error:
        await asyncio.wait_for(recognize_pcm(b'00', 'test-key', connect_factory=transport(socket)), .5)
    assert error.value.code == 'service_unavailable' and socket.closed
