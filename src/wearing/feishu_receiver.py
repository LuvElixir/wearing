"""Owned child-process lifecycle for Feishu events; no agent runs in the child."""
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import sys
import time


class FeishuReceiver:
    def __init__(self, receive, status):
        self.receive, self.status = receive, status
        self.children = {}
        self.retry_after = {}

    async def synchronize(self, rows):
        wanted = {row["identity_id"]: row for row in rows}
        for identity in list(self.children):
            child = self.children[identity]
            if identity not in wanted or child["revision"] != wanted[identity]["revision"] or child["process"].returncode is not None:
                await self.stop(identity)
        for identity, row in wanted.items():
            if identity in self.children or time.monotonic() < self.retry_after.get(identity, 0):
                continue
            process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name("feishu_worker.py")), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=128 * 1024)
            process.stdin.write((json.dumps({"app_id": row["bot_id"], "secret": row["secret"]}) + "\n").encode())
            await process.stdin.drain()
            self.children[identity] = {"process": process, "revision": row["revision"], "reader": asyncio.create_task(self._read(row, process))}

    async def _read(self, row, process):
        try:
            while line := await process.stdout.readline():
                message = json.loads(line)
                if message.get("kind") == "message":
                    event = message.get("event")
                    if not isinstance(event, dict):
                        continue
                    await self.receive(row, event)
                    process.stdin.write((json.dumps({"ack": (event.get("header") or {}).get("event_id")}) + "\n").encode())
                    await process.stdin.drain()
                elif message.get("kind") in {"connected", "reconnecting", "failed"}:
                    await self.status(row, message["kind"])
            await self.status(row, "failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.status(row, "failed")
        finally:
            self.retry_after[row["identity_id"]] = time.monotonic() + 30
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()

    async def stop(self, identity):
        child = self.children.pop(identity, None)
        if child is None:
            return
        child["reader"].cancel()
        with suppress(asyncio.CancelledError):
            await child["reader"]
        process = child["process"]
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

    async def close(self):
        for identity in list(self.children):
            await self.stop(identity)
