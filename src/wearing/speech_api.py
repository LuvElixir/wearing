"""Identity-scoped live PCM input. No partial result ever reaches the agent."""
import asyncio
from contextlib import suppress
import json
import logging
import re
import secrets
from time import perf_counter

from starlette.websockets import WebSocket, WebSocketDisconnect

from .capture_setup import speech_key
from .speech import MAX_SECONDS, SAMPLE_RATE, SpeechError, recognize_stream
from .usage import UsageError

PATH = "/api/voice/stream"
MAX_FRAME = 32000  # At most one second of signed 16-bit mono PCM.
logger = logging.getLogger(__name__)


async def first_message(socket):
    message = await asyncio.wait_for(socket.receive_text(), 3)
    if len(message) > 2048:
        raise ValueError()
    data = json.loads(message)
    if not isinstance(data, dict):
        raise ValueError()
    return data


def install_speech_routes(app, store, token, data_dir, browser_origin=None):
    active = set()

    @app.websocket(PATH)
    async def live(socket: WebSocket):
        origin = socket.headers.getlist("origin")
        expected = browser_origin or "http://" + socket.headers.get("host", "")
        if (origin and origin != [expected]) or socket.url.query:
            await socket.close(code=1008)
            return
        await socket.accept()
        lease = None
        try:
            start = await first_message(socket)
            identity, take = start.get("identity"), start.get("take")
            if (start.get("type") != "start" or not isinstance(start.get("token"), str)
                    or not secrets.compare_digest(start["token"], token)
                    or not isinstance(identity, str) or not isinstance(take, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", take)
                    or start.get("format") != "pcm_s16le_16000_mono"):
                raise ValueError()
            store.identity(identity)
            key = speech_key(data_dir)
            if not key:
                raise SpeechError("not_configured")
            lease = (identity, take)
            if lease in active or len(active) >= 2:
                lease = None
                raise SpeechError("busy")
            active.add(lease)
            await socket.send_json({"type": "ready", "take": take})
            import os
            recognize = None
            if os.environ.get("PAJIO_TRIAL_LIMITS") == "1":
                from .usage_speech import guarded_recognition
                async def recognize(chunks, api_key):
                    return await guarded_recognition(chunks, api_key, data_dir=data_dir, identity=identity, request_key="live:" + take, recognize=recognize_stream)
            await live_recognition(socket, take, key, recognize=recognize)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except (ValueError, TypeError, KeyError):
            await socket.close(code=1008)
        except (SpeechError, TimeoutError) as error:
            code = error.code if isinstance(error, SpeechError) else "timeout"
            logger.info("Voice stream stopped: code=%s", code)
            with suppress(WebSocketDisconnect, RuntimeError):
                await socket.send_json({"type": "error", "code": code, **({"message": UsageError(code).detail} if code.startswith("quota_") else {})})
                await socket.close(code=1011)
        finally:
            if lease:
                active.discard(lease)


async def live_recognition(socket, take, key, *, recognize=None):
    queue = asyncio.Queue(maxsize=30)  # Bounded startup/network backlog; never drop samples.
    total = 0
    finished = False
    finish_at = None

    async def read_audio():
        nonlocal total, finished, finish_at
        while True:
            message = await asyncio.wait_for(socket.receive(), 15)
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            chunk = message.get("bytes")
            if chunk is not None and not finished:
                if not chunk or len(chunk) > MAX_FRAME or len(chunk) % 2:
                    raise SpeechError("invalid_audio")
                total += len(chunk)
                if total > MAX_SECONDS * SAMPLE_RATE * 2:
                    raise SpeechError("duration_limit")
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    raise SpeechError("backpressure") from None
            elif message.get("text") and len(message["text"]) < 256 and not finished:
                end = json.loads(message["text"])
                if end != {"type": "finish", "bytes": total} or not total:
                    raise SpeechError("invalid_audio")
                finished = True
                finish_at = perf_counter()
                await queue.put(None)
                # Keep watching for cancellation/disconnection during finalization.
            else:
                raise SpeechError("invalid_audio")

    async def chunks():
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            yield chunk

    reader = asyncio.create_task(read_audio())
    recognition = asyncio.create_task((recognize or recognize_stream)(chunks(), key))
    try:
        async with asyncio.timeout(MAX_SECONDS + 30):
            done, _ = await asyncio.wait((reader, recognition), return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                await reader
            text = await recognition
            if not finished:
                raise SpeechError("invalid_response")
            await socket.send_json({"type": "final", "take": take, "text": text})
            logger.info("Voice stream finished: audio_ms=%d final_ms=%d",
                        round(total / (SAMPLE_RATE * 2) * 1000),
                        round((perf_counter() - finish_at) * 1000))
            await socket.close(code=1000)
    finally:
        reader.cancel()
        recognition.cancel()
        await asyncio.gather(reader, recognition, return_exceptions=True)
