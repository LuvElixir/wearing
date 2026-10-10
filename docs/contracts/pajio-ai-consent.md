# DeepSeek sharing consent

Candidate Core contract, 2026-10-10. Source and synthetic integration tests are not production or App acceptance. This change does not grant consent, deploy a service, or migrate an existing grant. It addresses prior disclosure and explicit permission for third-party AI processing described in [Apple guideline 5.1.2(i)](https://developer.apple.com/app-store/review/guidelines/#data-use-and-sharing).

## Authenticated API

`GET /api/ai-consent` and `POST /api/ai-consent` use the existing Core authentication, selected identity, and mutation CSRF token. Both responses are `Cache-Control: no-store`. The cloud `TenantBoundary` must have verified a private account owner: its `private_owner_scope` must equal `storage_scope`. The client cannot supply an owner in the body. Local development does not use this cloud consent ledger.

GET returns these fields:

```json
{
  "required": true,
  "provider": {
    "id": "deepseek",
    "name": "DeepSeek",
    "origin": "https://api.deepseek.com",
    "privacy_url": "https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html"
  },
  "policy_version": "deepseek-2026-10-10-v1",
  "disclosure": {
    "title": "允许 DeepSeek 处理本次 AI 功能所需的内容？",
    "purpose": "回答问题、整理记录和简报，以及执行你授权的 Agent 任务。",
    "data_categories": [
      "你提交的对话和任务内容",
      "完成请求所需且获准使用的记忆、文件及上下文",
      "任务读取的工具结果，包括可能含个人信息的设备画面和应用内容"
    ],
    "withdrawal": "可随时撤回，之后的新 AI 请求和后台调用会停止。已经发送给服务商的内容无法收回，进行中的回复可能已经传出部分内容。"
  },
  "accepted": false,
  "state": "not_granted",
  "revision": 0,
  "updated_at": null
}
```

`state` is `not_granted | accepted | revoked`. A policy-version change invalidates an old acceptance. `revision` is a nonnegative integer. `updated_at` is a finite positive Unix timestamp **in seconds, including fractional seconds**, or `null` before a decision.

POST accepts only:

```json
{
  "action": "accept",
  "policy_version": "deepseek-2026-10-10-v1",
  "expected_revision": 0,
  "request_id": "0123456789abcdef0123456789abcdef"
}
```

`action` is `accept | revoke`; `request_id` is 32 lowercase hexadecimal characters. Acceptance requires the current policy and revision. Revocation requires the current revision but can withdraw an older policy. Extra properties are rejected.

Success returns the **current** GET snapshot and `receipt: {request_id, action, revision, recorded_at}`. `recorded_at` is also Unix seconds with fractional seconds. A replay of an older accepted request after a separate withdrawal returns the current revoked state and the historical receipt; it never revives the grant. Same request ID with changed input is rejected. Clients must not infer current acceptance from the historical receipt alone.

After a lost POST response, fetch GET and show the current state. Do not automatically repeat a consent decision. A revision conflict likewise requires a fresh read and a new explicit action.

Fixed errors are `{code, detail}`:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 403 | `ai_consent_private_owner_required` | No verified private owner |
| 403 | `ai_consent_owner_changed` | Existing anchor belongs to a different account or instance |
| 409 | `ai_consent_revision_changed` | The policy or decision revision changed |
| 409 | `ai_consent_request_changed` | Same request ID was used for different input |
| 409 | `ai_consent_unavailable` | Private scope or ledger cannot be checked |
| 422 | `ai_consent_request_invalid` | Invalid decision input; Pydantic field validation may instead use its normal `detail` array |

Existing authentication failures can return 401/403 before this handler. No actor, tenant, instance, credentials, prompts, or file contents are returned by the consent API.

## Durable boundary and enforcement

`data/ai-consent.sqlite3` is private to the tenant service account. The first explicit decision atomically binds one immutable verified owner to the actual private `instance.json` and `data/instance-owner.json`. Each identity has its own revision and policy decision. Another owner, another identity without a decision, a copied database in another instance, a deleted instance, an unsafe ledger, and unsupported provider origins fail closed. GET alone creates no acceptance or owner binding.

Hosted `HermesRuntime` enables the guard independently of trial pricing. Authority is captured before editable provider dotenv is read. Both synchronous and asynchronous OpenAI-compatible dispatches reread the ledger, including auxiliary and child-agent clients. Only DeepSeek's exact HTTPS origin is supported. Existing redirect, unsupported transport, retry, and provider-fallback restrictions remain. A no-content DeepSeek models-list GET is the only SDK metadata exception; arbitrary GET bodies/queries cannot bypass consent. A completed withdrawal during a waiting usage reservation is rechecked before dispatch; that known unsent attempt records zero tokens rather than a fabricated provider receipt.

The Core task gate also verifies the stored task principal and the engine's `wearing.ai_consent_guard == "deepseek-v1"` capability before sending a task to Hermes. This prevents a newly protected Core from dispatching work through an old, unprotected engine. Capture organization stores the verified owner separately and uses the same protected managed interpreter. Existing ownerless organization jobs stop with originals retained.

| Trigger | Enforcement |
| --- | --- |
| Chat, onboarding first briefing, requested briefings | Task principal check, engine capability, then per-request SDK check |
| Scheduled work, recurring briefings, goals, queued messages | Inherited task principal and current decision at start; per-request SDK check thereafter |
| Auxiliary summarization, context compression, automated memory/model work, vision routing | Guarded SDK/auxiliary dispatch; an unsupported provider is rejected |
| Capture AI organization | Trusted owner at queueing and execution; guarded child interpreter |
| Manual memory edits, plain record saving, reading existing results | No model dispatch; available without granting AI consent |

Withdrawal prevents subsequent model requests after the decision is observed; it does not retract content already dispatched, guarantee interruption of an existing stream, cancel already running device operations, delete provider-held data, or disable non-AI network tools. A process dispatch racing with a withdrawal can already have passed its last admission check. The disclosure therefore states that already sent content cannot be recalled. Future speech/image-generation providers or other non-SDK AI transports require their own explicit policy and enforcement before activation; this is not blanket consent for all third parties.

## Verification and release boundary

Tests use real private-instance initialization, SQLite concurrency/restart/CAS, the actual `TenantBoundary` and FastAPI routes/CSRF, real Core task paths, capture jobs, and the installed OpenAI SDK with `httpx.MockTransport`. No paid model request or production account decision is performed. The fixture covers changed provider/owner, revoked background work, stale engine rejection, trial-disabled enforcement, unknown-result reads, and the budget-reservation withdrawal race.

Deployment must overlay the reviewed Core modules and restart the Core **and its managed Hermes engine** under the existing controlled service lifecycle. Preserve the empty/default-denied state. Readiness must prove the new engine capability and authenticated GET's ungranted state without submitting an acceptance. Activation-worker frozen packages and plans remain a separate release boundary.
