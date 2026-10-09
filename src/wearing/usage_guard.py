"""Pajio trial guard for the pinned Hermes OpenAI-compatible SDK transport.

Installed only in explicitly enabled tenant runtimes. SDK automatic retries are
zeroed on each actual SDK request: Hermes retries receive their own reservation.
Streams keep their slot until consumed/closed. A canceled/unknown receipt never
refunds the attempted-call quota. No payload, credentials or response text stored.
"""
import functools
from dataclasses import dataclass
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlparse

try:
    from .usage import UsageBook, UsageError
except ImportError:  # managed interpreter script
    from usage import UsageBook, UsageError


@dataclass(frozen=True)
class UsageGuardConfig:
    """Host authority, captured before loading editable provider configuration."""

    enabled: bool
    data_dir: Path | None = None
    identity: str | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise UsageError("quota_unavailable")
        if self.enabled and (self.data_dir is None or not self.data_dir.is_absolute()
                or self.data_dir.is_symlink() or not self.identity
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.identity)):
            raise UsageError("quota_unavailable")

    @classmethod
    def from_env(cls):
        directory = os.environ.get("PAJIO_USAGE_DATA_DIR")
        return cls(os.environ.get("PAJIO_TRIAL_LIMITS") == "1",
                   Path(directory) if directory else None,
                   os.environ.get("PAJIO_USAGE_IDENTITY"))


def _mapping(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def receipt(value):
    item = _mapping(value)
    usage = _mapping(item.get("usage"))
    if not usage and isinstance(item.get("response"), dict):
        usage = _mapping(item["response"].get("usage"))
    result = {}
    for output, names in (("input_tokens", ("prompt_tokens", "input_tokens")), ("output_tokens", ("completion_tokens", "output_tokens"))):
        for name in names:
            number = usage.get(name)
            if type(number) is int and 0 <= number <= 1_000_000_000:
                result[output] = number
                break
    return result


class _Stream:
    def __init__(self, inner, book, call_id):
        self.inner, self.book, self.call_id = inner, book, call_id
        self.usage = {}
        self.done = False

    def __getattr__(self, key):
        return getattr(self.inner, key)

    def finish(self, uncertain=False):
        if not self.done:
            self.book.settle(self.call_id, **self.usage, uncertain=uncertain)
            self.done = True

    def __iter__(self):
        try:
            for event in self.inner:
                self.usage.update(receipt(event))
                yield event
        except BaseException:
            self.finish(True)
            raise
        else:
            self.finish()

    def close(self):
        try:
            return self.inner.close()
        finally:
            self.finish(not self.done)

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        try:
            return self.inner.__exit__(*args)
        finally:
            self.finish(not self.done)


class _AsyncStream(_Stream):
    async def __aiter__(self):
        try:
            async for event in self.inner:
                self.usage.update(receipt(event))
                yield event
        except BaseException:
            self.finish(True)
            raise
        else:
            self.finish()

    async def close(self):
        try:
            return await self.inner.close()
        finally:
            self.finish(not self.done)

    async def __aenter__(self):
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, *args):
        try:
            return await self.inner.__aexit__(*args)
        finally:
            self.finish(not self.done)


def wrap_sdk_request(original, book, identity, *, asynchronous=False):
    def prepare(client, options):
        if options.method.lower() == "get":
            return None, options
        # Fail closed for other native API families rather than imply coverage.
        path = urlparse(str(options.url)).path.rstrip("/")
        if not path.endswith(("/chat/completions", "/completions", "/embeddings", "/responses")):
            raise UsageError("quota_provider")
        copied = options.model_copy(deep=True) if hasattr(options, "model_copy") else options.copy(deep=True)
        copied.max_retries = 0
        copied.follow_redirects = False
        body = copied.json_data if isinstance(copied.json_data, dict) else {}
        extra = copied.extra_json if isinstance(copied.extra_json, dict) else {}
        effective = {**body, **extra}
        if path.endswith("/chat/completions"):
            # A request count cap is finite only with bounded output per call.
            field = "max_completion_tokens" if "max_completion_tokens" in effective else "max_tokens"
            limit = effective.get(field)
            body[field] = min(limit, 8192) if type(limit) is int and limit > 0 else 8192
            extra[field] = body[field]
        if path.endswith("/responses"):
            limit = effective.get("max_output_tokens")
            body["max_output_tokens"] = min(limit, 8192) if type(limit) is int and limit > 0 else 8192
            extra["max_output_tokens"] = body["max_output_tokens"]
        copied.json_data = body
        copied.extra_json = extra
        call_id = book.reserve(identity, "model", uuid.uuid4().hex, provider=urlparse(str(client.base_url)).hostname, model=effective.get("model"))
        return call_id, copied

    if asynchronous:
        @functools.wraps(original)
        async def run(client, cast_to, options, **kwargs):
            call_id, copied = prepare(client, options)
            if call_id is None:
                return await original(client, cast_to, copied, **kwargs)
            try:
                response = await original(client, cast_to, copied, **kwargs)
                if kwargs.get("stream"):
                    return _AsyncStream(response, book, call_id)
                book.settle(call_id, **receipt(response))
                return response
            except BaseException:
                book.settle(call_id, uncertain=True)
                raise
    else:
        @functools.wraps(original)
        def run(client, cast_to, options, **kwargs):
            call_id, copied = prepare(client, options)
            if call_id is None:
                return original(client, cast_to, copied, **kwargs)
            try:
                response = original(client, cast_to, copied, **kwargs)
                if kwargs.get("stream"):
                    return _Stream(response, book, call_id)
                book.settle(call_id, **receipt(response))
                return response
            except BaseException:
                book.settle(call_id, uncertain=True)
                raise
    return run


def guard_agent(agent, *, enabled):
    if not enabled:
        return agent
    if getattr(agent, "api_mode", None) != "chat_completions" or getattr(agent, "provider", None) in {"moa", "bedrock", "copilot", "openai-codex"}:
        raise UsageError("quota_provider")
    # Provider fallback may select a different transport after construction.
    agent._fallback_chain = []
    agent._fallback_model = None
    agent._fallback_index = 0
    return agent


_installed_config = None


def install_usage_guard(config: UsageGuardConfig):
    global _installed_config
    if not isinstance(config, UsageGuardConfig):
        raise UsageError("quota_unavailable")
    if _installed_config is not None:
        if config != _installed_config:
            raise UsageError("quota_unavailable")
        return True
    if not config.enabled:
        return False
    book = UsageBook(config.data_dir, enabled=True)
    book.recover()
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    SyncAPIClient.request = wrap_sdk_request(SyncAPIClient.request, book, config.identity)
    AsyncAPIClient.request = wrap_sdk_request(AsyncAPIClient.request, book, config.identity, asynchronous=True)
    # Native auxiliary adapters have a chat-shaped facade but bypass the SDK.
    # Gate both initial selection and later retry/fallback dispatch.
    from agent import auxiliary_client
    from openai import OpenAI, AsyncOpenAI
    def guarded_client(client):
        if not isinstance(client, (OpenAI, AsyncOpenAI)):
            raise UsageError("quota_provider")
    resolve = auxiliary_client._resolve_call_client
    @functools.wraps(resolve)
    def resolve_aux(*args, **kwargs):
        route = resolve(*args, **kwargs)
        guarded_client(route.client)
        return route
    auxiliary_client._resolve_call_client = resolve_aux
    def guard_relay(original):
        @functools.wraps(original)
        def relay(client, *args, **kwargs):
            guarded_client(client)
            return original(client, *args, **kwargs)
        return relay
    for name in ("_relay_sync_completion", "_relay_sync_stream", "_relay_async_completion"):
        setattr(auxiliary_client, name, guard_relay(getattr(auxiliary_client, name)))
    # Child agents and capture organization must obey the same transport gate.
    from run_agent import AIAgent
    original_init = AIAgent.__init__
    @functools.wraps(original_init)
    def init(agent, *args, **kwargs):
        kwargs["fallback_model"] = None
        original_init(agent, *args, **kwargs)
        guard_agent(agent, enabled=config.enabled)
    AIAgent.__init__ = init
    _installed_config = config
    return True
