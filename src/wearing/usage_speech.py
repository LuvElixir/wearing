"""Admission at the Seed-ASR network boundary, sharing the tenant trial ledger."""
import uuid

from .usage import UsageBook, UsageError


async def guarded_recognition(chunks, key, *, data_dir, identity, request_key=None, reserve_ms=180_000, recognize=None):
    from .speech import SpeechError, recognize_stream, SAMPLE_RATE
    book = UsageBook(data_dir)
    if not book.enabled:
        return await (recognize or recognize_stream)(chunks, key)
    try:
        remaining = book.snapshot(identity)["resources"]["speech"]["ms_remaining"]
        if remaining <= 0:
            raise UsageError("quota_exhausted")
        allowance = min(reserve_ms, remaining)
        call_id = book.reserve(identity, "speech", request_key or uuid.uuid4().hex, reserve_ms=allowance, provider="volcengine-seedasr")
    except UsageError as error:
        raise SpeechError(error.code) from None
    total = 0
    async def bounded():
        nonlocal total
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise SpeechError("invalid_audio")
            proposed = total + len(chunk)
            if proposed * 1000 > allowance * SAMPLE_RATE * 2:
                raise SpeechError("quota_exhausted")
            total = proposed
            yield chunk
    try:
        result = await (recognize or recognize_stream)(bounded(), key)
    except BaseException:
        # The provider may have accepted audio: preserve the whole reservation.
        book.settle(call_id, uncertain=True)
        raise
    book.settle(call_id, measured_ms=(total * 1000 + SAMPLE_RATE * 2 - 1) // (SAMPLE_RATE * 2))
    return result
