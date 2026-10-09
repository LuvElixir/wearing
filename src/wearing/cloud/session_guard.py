"""Cancel waits when the server no longer admits their authenticated session."""
import asyncio


class SessionRevoked(ValueError):
    pass


async def checked_wait(awaitable, valid, *, interval=0.25, cleanup=None):
    if valid is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            if not valid():
                raise SessionRevoked('登录权限已失效。')
            done, _ = await asyncio.wait([task], timeout=interval)
            if task in done:
                if not valid():
                    raise SessionRevoked('登录权限已失效。')
                return task.result()
    except BaseException:
        if cleanup is not None and task.done() and not task.cancelled() and task.exception() is None:
            try:
                await cleanup(task.result())
            except Exception:
                pass  # Preserve the revocation, database or cancellation failure.
        raise
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
