"""Authenticated live-audio tunnel to the caller's fixed tenant route."""
import asyncio
import json
import logging
import re

from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

from ..speech_api import MAX_FRAME, first_message
from .session_guard import checked_wait

PATH = "/api/voice/stream"


def voice_endpoint(origin, store, credentials, *, connector=connect, ssl_context=None):
    async def relay(socket):
        if socket.url.query or socket.headers.getlist("origin") not in ([], [origin]):
            await socket.close(code=1008)
            return
        await socket.accept()
        pumps = []
        code = 1000
        try:
            start = await first_message(socket)
            access = start.pop("access", None)
            expected_tenant = start.pop('expected_tenant', None)
            if access is None and socket.headers.getlist("origin") == [origin]:
                access = socket.session.get("sid")
            if not isinstance(access, str) or not re.fullmatch(r"[A-Za-z0-9_-]{64}", access):
                raise ValueError()
            current = store.session(access)
            if current is None or (expected_tenant is not None and expected_tenant != current.tenant_id):
                raise ValueError()
            pinned = socket.session.get('native_tenant')
            if pinned and pinned != current.tenant_id:
                raise ValueError()
            def valid():
                latest = store.session(access)
                return latest is not None and latest.user_id == current.user_id and latest.tenant_id == current.tenant_id

            route, key = credentials(current)
            if route is None:
                raise ValueError()
            upstream = route["upstream"].replace("https://", "wss://", 1).replace("http://", "ws://", 1)
            async with asyncio.timeout(210):
                if ssl_context is not None and not upstream.startswith('wss://'):
                    raise ValueError('Private TLS requires a secure upstream.')
                async with connector(upstream + PATH, origin=origin,
                                     **({'ssl': ssl_context} if ssl_context is not None else {}),
                                     additional_headers={"Authorization": "Bearer " + key, "X-Wearing-Tenant": current.tenant_id},
                                     proxy=None, open_timeout=5, close_timeout=1, max_size=65536, max_queue=8,
                                     logger=logging.Logger("pajio.voice.gateway", logging.WARNING)) as remote:
                    await checked_wait(remote.send(json.dumps(start)), valid)

                    async def upload():
                        while True:
                            message = await socket.receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            data = message.get("bytes") if message.get("bytes") is not None else message.get("text", "")
                            if not valid() or not data or len(data) > (MAX_FRAME if isinstance(data, bytes) else 2048):
                                raise ValueError()
                            await checked_wait(remote.send(data), valid)

                    async def download():
                        async for data in remote:
                            if not valid() or not isinstance(data, str) or len(data) > 65536:
                                raise ValueError()
                            await checked_wait(socket.send_text(data), valid)

                    async def revoked():
                        while True:
                            await asyncio.sleep(0.25)
                            if not valid():
                                raise ValueError()

                    pumps = [asyncio.create_task(upload()), asyncio.create_task(download()), asyncio.create_task(revoked())]
                    done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        await task
        except (ValueError, KeyError, TypeError):
            code = 1008
        except Exception:
            # Credentials, provider headers, audio and transcripts never enter logs.
            code = 1011
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            try:
                await socket.close(code=code)
            except (RuntimeError, WebSocketDisconnect):
                pass
    return relay
