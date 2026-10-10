# Pajio invitation browser boundary review — 2026-10-10

This review used synthetic local browser fixtures and local gateway tests. It did not create production accounts, use real passwords, operate a cloud device, or modify live server logging. Root owns deployment and real desktop / iOS acceptance.

Subsequent edge deployment, real WKWebView login, C registration, and iOS native return are recorded in the [combined release evidence](pajio-invitation-release-2026-10-10.md). This document preserves the earlier fixture boundary and does not override that later evidence.

## Native registration completion

Chrome 154.0.8037.99, isolated Playwright CLI browser, intercepted `https://pajio-csp.invalid` fixture:

| Same-origin form POST → 303 destination | `form-action` addition | Browser result |
| --- | --- | --- |
| `pajio://auth` | none | CSP `form-action` violation |
| `pajio://auth` | `pajio://auth` | CSP `form-action` violation |
| `pajio://auth` | `pajio://auth/` | CSP `form-action` violation |
| `pajio://auth` | `pajio://auth:*` | CSP `form-action` violation |
| `pajio://auth` | broad `pajio:` (test fixture only) | Reached external protocol handler |

No broad scheme permission was shipped. The exact generated `native_ready` HTML was then rendered and its “返回 Pajio” anchor clicked. The browser reached the external protocol handler without a CSP violation. The isolated browser has no registered Pajio handler, so this proves the browser policy boundary, not real app handoff.

The shipped completion response stays on the same origin, is `no-store` / `no-referrer`, contains no scripts or third-party resources, and has `form-action 'none'`. Its only link is rebuilt from fixed `pajio://auth` and validated `code` / `state`. The existing PKCE exchange remains one-use. Ordinary OIDC callbacks are unchanged.

## Form Origin diagnosis

Chrome 154.0.8037.99, separate isolated fixture, ordinary HTML form POST to its same-origin `/join/existing`:

| Response Referrer-Policy | Observed request Origin | Cookie present | Exact-origin check |
| --- | --- | --- | --- |
| `no-referrer` | `null` | yes | rejected |
| `same-origin` | fixture HTTPS origin | yes | accepted |

Only header categories and booleans were recorded. The fixtures used synthetic cookies and form values. No real cookie, body, credentials, or invite was logged. Playwright WebKit was unavailable locally; this is Chrome evidence, not a WebKit pass.

The app change lets invitation HTML explicitly return `same-origin`. `EntryHeaders` preserves it only for `/join`, `/join/check`, `/join/create`, `/join/login`, `/join/existing`, and `/auth/mobile/start`, when the response is HTML and already requests exactly `same-origin`. All other responses retain `no-referrer`, including native completion. Exact Origin, cookie binding, and one-use form ticket checks remain unchanged; null, missing, and foreign Origins still fail.

Root subsequently reported a remaining real WKWebView 400 and identified two public response headers: app `same-origin`, followed by edge `no-referrer`. The edge template still appended a second policy. The latter valid policy governs the browser; checking an ASGI response or checking that a combined header merely contains `same-origin` misses this deployment boundary. See [Fetch Origin header algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header) and [Referrer-Policy header parsing](https://www.w3.org/TR/referrer-policy/#parse-referrer-policy-from-header).

## Edge correction acceptance contract

Root is implementing the edge correction; this document does not assert it is deployed or that WKWebView passed.

1. Hide the upstream Referrer-Policy and emit exactly one final header on the public Pajio gateway host.
2. Preserve `same-origin` only for the exact invitation form routes and upstream value `same-origin` (optionally also HTML content type). All other cases default to `no-referrer`. Route alone is insufficient: `/join/create` can return the native completion page.
3. Do not broaden the IdP host, all `/join/` prefixes, CSP, allowed Origin values, cookie policy, or public provider routes.
4. From the public HTTPS endpoint, inspect the complete header list and require exactly `['same-origin']` on fresh `/join` and invitation/account form responses. Require exactly `['no-referrer']` on native completion, login redirects, and other responses. A string containment assertion is insufficient.
5. In a fresh desktop WKWebView flow, verify `/join` → existing-account action reaches the IdP. Then verify real invite check / account creation separately; changing only existing-account to GET would mask an unresolved registration POST failure.
6. On iOS, verify account creation completes in the system browser, “返回 Pajio” hands off, and PKCE exchange establishes the intended private workspace. Do not count ASGI or synthetic browser proof as this real acceptance.

## Local validation and frozen app source

`pytest -q tests/test_invitation_gateway.py tests/test_mobile_gateway.py tests/test_gateway.py tests/test_registration.py`: **64 passed**, one existing Authlib deprecation warning. The invitation tests use `create_gateway_app`, including the real `EntryHeaders`, and cover form header preservation plus null / missing / foreign Origin rejection. `git diff --check` passed.

| File | SHA-256 |
| --- | --- |
| `src/wearing/cloud/join.py` | `5550ad0e8bf683766f2554f0d618eaca9a3a8133d0bac15f4ebdcc45f3f8452a` |
| `src/wearing/cloud/gateway.py` | `6ea3857a41166096a319088aede5d331e250d6dd63ce02f17046ca1379f6e7f5` |
| `tests/test_invitation_gateway.py` | `c1eb0a2296027dee6d0d3ecdc700fdaf1f11c2d09ec8516206f1b979fac29d3e` |

All temporary synthetic browser sessions were closed. No recurring monitor was installed.
