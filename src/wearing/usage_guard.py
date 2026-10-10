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
    consent_required: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.consent_required) is not bool:
            raise UsageError("quota_unavailable")
        if (self.enabled or self.consent_required) and (self.data_dir is None or not self.data_dir.is_absolute()
                or self.data_dir.is_symlink() or not self.identity
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.identity)):
            raise UsageError("quota_unavailable")

    @classmethod
    def from_env(cls):
        directory = os.environ.get("PAJIO_USAGE_DATA_DIR")
        return cls(os.environ.get("PAJIO_TRIAL_LIMITS") == "1",
                   Path(directory) if directory else None,
                   os.environ.get("PAJIO_USAGE_IDENTITY"),
                   os.environ.get("PAJIO_AI_CONSENT_REQUIRED") == "1")


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
    # DeepSeek exposes top-level cache counters. OpenAI-compatible Responses
    # and chat use nested details. Never infer a cache hit from request content.
    total = result.get("input_tokens")
    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    for details_key in ("prompt_tokens_details", "input_tokens_details"):
        if hit is None:
            hit = _mapping(usage.get(details_key)).get("cached_tokens")
    valid = lambda number: type(number) is int and 0 <= number <= 1_000_000_000
    if total is not None:
        if valid(hit) and hit <= total and (miss is None or valid(miss) and hit + miss == total):
            result["cached_input_tokens"] = hit
        elif hit is None and valid(miss) and miss <= total:
            result["cached_input_tokens"] = total - miss
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


def wrap_sdk_request(original, book, identity, *, asynchronous=False, consent=None):
    def prepare(client, options):
        # Use the SDK's own resolution: an absolute options.url bypasses
        # base_url. Never send its credentials or apply its rates elsewhere.
        from httpx import InvalidURL, URL
        def origin(url):
            return url.scheme, url.host, url.port or {"https": 443, "http": 80}.get(url.scheme)
        try:
            base = URL(client.base_url)
            destination = client._prepare_url(options.url)
            if (base.scheme not in ("http", "https") or not base.host
                    or base.userinfo or destination.userinfo
                    or origin(destination) != origin(base)):
                raise ValueError("Different provider origin")
            host = client._build_headers(options).get("host")
            if host is not None:
                host_url = URL(base.scheme + "://" + host)
                if (origin(host_url) != origin(base) or host_url.userinfo
                        or host_url.raw_path != b"/" or host_url.fragment):
                    raise ValueError("Different provider Host")
        except (InvalidURL, TypeError, ValueError):
            raise UsageError("quota_provider") from None
        copied = options.model_copy(deep=True) if hasattr(options, "model_copy") else options.copy(deep=True)
        copied.follow_redirects = False
        provider_origin = str(destination.copy_with(path='', query=None, fragment=None)).rstrip('/')
        if options.method.lower() == "get":
            if consent is not None:
                from wearing.ai_consent import ConsentError, PROVIDER
                # The one metadata call allowed before a decision contains no
                # prompt or query. A custom GET must not become an AI-data bypass.
                if (provider_origin != PROVIDER['origin'] or not destination.path.rstrip('/').endswith('/models')
                        or destination.query or getattr(options, 'params', None)
                        or options.json_data or getattr(options, 'extra_json', None)):
                    raise ConsentError('ai_provider_not_supported', 403)
            return None, copied
        # Fail closed for other native API families rather than imply coverage.
        path = destination.path.rstrip("/")
        if not path.endswith(("/chat/completions", "/completions", "/embeddings", "/responses")):
            raise UsageError("quota_provider")
        copied.max_retries = 0
        body = copied.json_data if isinstance(copied.json_data, dict) else {}
        extra = copied.extra_json if isinstance(copied.extra_json, dict) else {}
        effective = {**body, **extra}
        # One reservation covers one context and one completion. Do not accept
        # multi-choice/best-of/batched requests that silently multiply the bound.
        if any(key in effective and effective[key] is not None and (type(effective[key]) is not int or effective[key] != 1) for key in ("n", "best_of")):
            raise UsageError("quota_provider")
        for key in ("n", "best_of"):
            if key in effective and effective[key] is None:
                body[key] = extra[key] = 1
        if path.endswith(("/embeddings", "/completions")) and not path.endswith("/chat/completions"):
            prompt = effective.get("input" if path.endswith("/embeddings") else "prompt")
            if isinstance(prompt, list) and prompt and not all(type(item) is int for item in prompt) and len(prompt) != 1:
                raise UsageError("quota_provider")
        output_tokens = 0
        if path.endswith("/completions"):
            # A request count cap is finite only with bounded output per call.
            field = "max_completion_tokens" if "max_completion_tokens" in effective else "max_tokens"
            limit = effective.get(field)
            body[field] = min(limit, 8192) if type(limit) is int and limit > 0 else 8192
            extra[field] = body[field]
            output_tokens = body[field]
            # Ensure the alternate cap cannot override the enforced limit.
            if field == "max_completion_tokens" and "max_tokens" in effective:
                body["max_tokens"] = extra["max_tokens"] = output_tokens
            if effective.get("stream") and path.endswith("/chat/completions"):
                stream_options = effective.get("stream_options")
                body["stream_options"] = extra["stream_options"] = {**(stream_options if isinstance(stream_options, dict) else {}), "include_usage": True}
        if path.endswith("/responses"):
            limit = effective.get("max_output_tokens")
            body["max_output_tokens"] = min(limit, 8192) if type(limit) is int and limit > 0 else 8192
            extra["max_output_tokens"] = body["max_output_tokens"]
            output_tokens = body["max_output_tokens"]
        copied.json_data = body
        copied.extra_json = extra
        if consent is not None:
            consent.require(identity, origin=provider_origin)
        call_id = book.reserve(identity, "model", uuid.uuid4().hex, provider=destination.host, model=effective.get("model"), reserve_output_tokens=output_tokens) if book is not None else None
        if consent is not None and call_id is not None:
            try:
                # A contended budget transaction may wait. Re-read after it,
                # immediately before handing the request to the SDK transport.
                consent.require(identity, origin=provider_origin)
            except BaseException:
                # No SDK send has happened: this specific attempt used zero tokens.
                book.settle(call_id, input_tokens=0, output_tokens=0, cached_input_tokens=0)
                raise
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
    if not config.enabled and not config.consent_required:
        return False
    book = UsageBook(config.data_dir, enabled=True) if config.enabled else None
    if book is not None: book.recover()
    consent = None
    if config.consent_required:
        from wearing.ai_consent import ConsentBook
        consent = ConsentBook(config.data_dir)
    from openai._base_client import SyncAPIClient, AsyncAPIClient
    SyncAPIClient.request = wrap_sdk_request(SyncAPIClient.request, book, config.identity, consent=consent)
    AsyncAPIClient.request = wrap_sdk_request(AsyncAPIClient.request, book, config.identity, asynchronous=True, consent=consent)
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
        guard_agent(agent, enabled=config.enabled or config.consent_required)
    AIAgent.__init__ = init
    _installed_config = config
    return True
