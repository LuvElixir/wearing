"""Doubao Seed-ASR 2 utterance adapter for saved mobile recordings.

Explicit requests only; no background replay, redirect, fallback or paid retry.
Streaming microphone transport is separate, not implied by this API.
"""
import asyncio
import gzip
import logging
import struct
import io
import json
from pathlib import Path
from time import perf_counter
import uuid
import wave


from .capture_setup import PROVIDER, speech_key

STREAM_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
STREAM_RESOURCE = "volc.seedasr.sauc.duration"
MAX_SECONDS = 180
SAMPLE_RATE = 16000
MAX_BYTES = 15 * 1024 * 1024


class SpeechError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def decode_wav(path):
    """Decode into bounded mono PCM; never modify or delete the source."""
    import av
    try:
        if Path(path).stat().st_size > MAX_BYTES:
            raise SpeechError("invalid_audio")
        pcm = bytearray()
        def append(frame):
            if len(pcm) + frame.samples * 2 > MAX_SECONDS * SAMPLE_RATE * 2:
                raise SpeechError("duration_limit")
            # A PyAV plane may include alignment padding after valid samples.
            pcm.extend(bytes(frame.planes[0])[:frame.samples * 2])
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise SpeechError("invalid_audio")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    append(converted)
            for converted in resampler.resample(None):
                append(converted)
        if not pcm:
            raise SpeechError("invalid_audio")
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(SAMPLE_RATE)
            audio.writeframes(pcm)
        return output.getvalue(), len(pcm) / (SAMPLE_RATE * 2)
    except SpeechError:
        raise
    except Exception:
        raise SpeechError("invalid_audio") from None


def request_packet(payload, sequence, *, audio=False, final=False):
    data = gzip.compress(payload)
    flags = 3 if final else 1
    header = bytes((0x11, ((2 if audio else 1) << 4) | flags, 0x11, 0))
    return header + struct.pack(">iI", -sequence if final else sequence, len(data)) + data


def response_packet(message):
    """Parse the documented v1 binary envelope with bounded decompression."""
    if not isinstance(message, bytes) or len(message) < 8 or message[0] >> 4 != 1:
        raise SpeechError("invalid_response")
    size = (message[0] & 15) * 4
    kind, flags = message[1] >> 4, message[1] & 15
    serialization, compression = message[2] >> 4, message[2] & 15
    if size < 4 or size > len(message) or kind not in (9, 15):
        raise SpeechError("invalid_response")
    cursor = size + (4 if flags & 1 else 0) + (4 if flags & 4 else 0)
    if kind == 15:
        if len(message) < cursor + 8:
            raise SpeechError("invalid_response")
        code = struct.unpack_from(">I", message, cursor)[0]
        if code == 45000030:
            raise SpeechError("service_not_enabled")
        if code == 20000003:
            raise SpeechError("no_speech")
        raise SpeechError("service_unavailable")
    if len(message) < cursor + 4:
        raise SpeechError("invalid_response")
    payload_size = struct.unpack_from(">I", message, cursor)[0]
    payload = message[cursor + 4:]
    if payload_size != len(payload) or len(payload) > 1024 * 1024:
        raise SpeechError("invalid_response")
    try:
        if compression == 1:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                payload = compressed.read(1024 * 1024 + 1)
        elif compression != 0:
            raise SpeechError("invalid_response")
        if serialization != 1 or len(payload) > 1024 * 1024:
            raise SpeechError("invalid_response")
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise SpeechError("invalid_response")
        if body.get("code", 0) not in (0, 20000000):
            raise SpeechError("service_unavailable")
        return body, bool(flags & 2)
    except (ValueError, OSError, EOFError):
        raise SpeechError("invalid_response") from None


async def recognize_pcm(pcm, key, *, connect_factory=None):
    """One isolated ASR session. Only the final package may become a draft.

    This accepts a completed recording today. Chunked microphone input will use
    the same protocol later, with capture-time pacing rather than delayed upload.
    """
    if not pcm or len(pcm) % 2:
        raise SpeechError("invalid_audio")
    if len(pcm) > MAX_SECONDS * SAMPLE_RATE * 2:
        raise SpeechError("duration_limit")
    async def chunks():
        for offset in range(0, len(pcm), 6400):
            yield pcm[offset:offset+6400]
    return await recognize_stream(chunks(), key, connect_factory=connect_factory)


async def recognize_stream(chunks, key, *, connect_factory=None):
    """Consume live PCM as it arrives; only an explicit end produces a final.

    The sentence endpoint preserves the same recognition mode as file input.
    No model command, automatic retry, or transcript storage occurs here.
    """
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus, WebSocketException
    factory = connect_factory or connect
    headers = {"X-Api-Key": key, "X-Api-Resource-Id": STREAM_RESOURCE,
               "X-Api-Request-Id": str(uuid.uuid4())}
    body = {"user": {"uid": "wearing"},
            "audio": {"format": "pcm", "codec": "raw", "rate": SAMPLE_RATE, "bits": 16, "channel": 1},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "enable_ddc": False, "result_type": "full"}}
    try:
        async with asyncio.timeout(MAX_SECONDS + 45):
            async with factory(STREAM_URL, additional_headers=headers, proxy=None,
                               open_timeout=10, close_timeout=2, max_size=1024*1024,
                               logger=logging.Logger("wearing.speech.transport", logging.WARNING)) as socket:
                await socket.send(request_packet(json.dumps(body).encode(), 1))
                response_packet(await socket.recv())
                async def send_audio():
                    sequence, total = 2, 0
                    async for chunk in chunks:
                        if not isinstance(chunk, bytes) or not chunk or len(chunk) % 2 or len(chunk) > 32000:
                            raise SpeechError("invalid_audio")
                        total += len(chunk)
                        if total > MAX_SECONDS * SAMPLE_RATE * 2:
                            raise SpeechError("duration_limit")
                        await socket.send(request_packet(chunk, sequence, audio=True))
                        sequence += 1
                        await asyncio.sleep(0)
                    if not total:
                        raise SpeechError("no_speech")
                    await socket.send(request_packet(b"", sequence, audio=True, final=True))
                async def receive_result():
                    while True:
                        result, final = response_packet(await socket.recv())
                        if final:
                            text = result.get("result", {}).get("text")
                            if not isinstance(text, str) or len(text) > 12000:
                                raise SpeechError("invalid_response")
                            if not text.strip():
                                raise SpeechError("no_speech")
                            return text.strip()
                sender = asyncio.create_task(send_audio())
                receiver = asyncio.create_task(receive_result())
                try:
                    _, text = await asyncio.gather(sender, receiver)
                    return text
                finally:
                    sender.cancel()
                    receiver.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
    except SpeechError:
        raise
    except InvalidStatus as error:
        code = "service_not_enabled" if error.response.status_code in (401,403) else "service_unavailable"
        raise SpeechError(code) from None
    except (WebSocketException, TimeoutError, OSError, ValueError, AttributeError):
        raise SpeechError("service_unavailable") from None


async def transcribe_file(path, data_dir):
    started = perf_counter()
    key = speech_key(data_dir)
    if not key:
        raise SpeechError("not_configured")
    audio, duration = await asyncio.to_thread(decode_wav, path)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    decoded = perf_counter()
    text = await recognize_pcm(pcm, key)
    finished = perf_counter()
    return {"text": text, "provider": PROVIDER, "mode": "recorded-utterance", "duration": duration,
            "timings": {"decode_ms": round((decoded-started)*1000),
                        "recognition_ms": round((finished-decoded)*1000),
                        "total_ms": round((finished-started)*1000)}}
