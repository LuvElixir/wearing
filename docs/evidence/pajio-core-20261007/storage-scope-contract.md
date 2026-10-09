# Account-bound browser storage

## Trust boundary

Authenticated cloud `GET /api/bootstrap` includes `storage_scope`, a stable 64-character lowercase SHA-256 identifier derived from a domain-separated tuple of the authenticated user ID and tenant ID. It contains no bearer token, session ID, or other login credential. Signing in again as the same account and tenant returns the same value; either account or tenant changing returns a different value.

The gateway constructs `X-Pajio-Storage-Scope` itself from the validated session. A client-supplied header, duplicate header, or query value is never forwarded as authority. The worker accepts the internal header only after its existing internal Bearer and tenant boundary pass. It rejects duplicate or malformed values and removes the internal header from downstream request headers, exposing the verified value only through ASGI `scope['pajio.storage_scope']`.

The optional header remains absent for existing private preview requests. In that case bootstrap explicitly returns `storage_scope: null`; this is not evidence of a cloud account boundary.

## Web / retained WebView consumer contract

Persistent drafts, pending submissions, voice receipt state, current identity, and any other account content must wait until authenticated bootstrap resolves. Storage keys must include both the trusted `storage_scope` and identity. A cloud bootstrap without a valid scope must not fall back to identity-only persistent keys. In-memory UI is an acceptable temporary fallback.

Do not automatically migrate old unscoped cloud draft keys into a newly authenticated account: their owner cannot be proven. Account changes must detach old callbacks and reset in-memory state before reading the new namespace. Tokens must never be written to these storage keys.

Native SQLite already scopes account content by endpoint, native user, tenant, and identity. This change closes the separate retained WebView `localStorage` boundary, which otherwise survives native component remounts.

## Regression evidence

`tests/test_native_storage_boundary.py` uses fake OIDC and a real isolated worker app without an engine. It verifies spoof rejection, cookie/Bearer consistency, stable relogin, same-tenant account separation, changed-tenant separation, old-tenant rejection, strict worker header validation, and missing-scope private preview compatibility.

Validation on 2026-10-08:

```sh
.venv/bin/pytest -q tests/test_native_storage_boundary.py tests/test_mobile_gateway.py tests/test_gateway_voice.py tests/test_private_preview.py
```

Result: **21 passed**. This verifies the backend contract; cross-account browser draft behavior also requires the matching Web consumer changes and UI acceptance.
