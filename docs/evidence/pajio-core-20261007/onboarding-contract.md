# Pajio first-run context API — 2026-10-09

This contract stores optional self-selected facts and preferences. It does not connect an app, grant access to content, trigger an agent, enable a schedule, or send a notification. No MBTI/personality inference or free-text profile field is accepted.

## Scope and lifecycle

- `GET /api/onboarding` and `POST /api/onboarding` use the host's existing authentication, Origin/CSRF, and identity gates.
- Both reads and writes additionally bind to the trusted account owner (`local` for local mode, validated server storage scope for cloud mode) and current identity. The body accepts neither owner nor identity. Missing cloud owner is `401`.
- Storage is two tables in the existing `wearing.sqlite3`: `onboarding_profiles` and `onboarding_requests`; both have compound owner/identity keys.
- A profile is `draft`, `completed`, or `skipped`. A missing row is represented as revision `0`, `draft`, step `0`, empty values, and null timestamps, without writing a row.
- Draft choices are resumable but do not enter agent context or briefing interests. Only the final completed snapshot is used.
- Reopening completed settings is a local edit. `completed → draft/skipped` is rejected with `409`; exiting without saving leaves the prior confirmed profile active. To clear choices, explicitly save a new completed all-empty/null snapshot. That changes future profile use, not past chat/task history.
- First-run skip stores `skipped` and empties values. It also removes draft choice values from old mutation receipts, retaining only non-content proof and hashed request fingerprints. Replaying an abandoned draft request after skip returns `409`, so a late retry cannot resurrect choices. No third-party authorization is revoked by skip.
- A skipped profile can later become draft or completed through a new explicit request. Completed edits stay completed.

## GET response

```json
{
  "schema": 1,
  "identity_id": "daily",
  "revision": 0,
  "status": "draft",
  "step": 0,
  "values": {
    "roles": [],
    "apps": [],
    "interests": [],
    "reply_detail": null,
    "reply_tone": null
  },
  "source": "self_selected",
  "confirmed_at": null,
  "updated_at": null,
  "recommend_onboarding": true
}
```

`source` describes this collection channel; an empty list/null is unknown, never an asserted self-report. A completed snapshot has one confirmation timestamp for its nonempty fields. Agent data repeats `source` and `confirmed_at` per nonempty field. No confidence score or inferred personality is invented.

`recommend_onboarding`:

- Existing `draft`: true; resume saved step.
- Existing `completed` or `skipped`: false.
- No record: true only if there are no owner-visible tasks; no identity-shared life records, briefing preference row, or media assets; no owner-visible goals/schedules; and no identity USER.md/MEMORY.md content or workspace entry. This is an existence check, not source import or proof the model has read any content. Another owner's private task/goal/schedule does not suppress the current account's onboarding. Identity-shared existing records do suppress it.
- Unreadable existing filesystem storage suppresses automatic prompting rather than assuming the account is empty. Settings can still be opened manually.

## POST request and receipt

```json
{
  "revision": 0,
  "request_key": "onboarding-unique-save-001",
  "status": "completed",
  "step": 5,
  "values": {
    "roles": ["employed"],
    "apps": ["wechat", "feishu"],
    "interests": ["design", "reading"],
    "reply_detail": "brief",
    "reply_tone": null
  }
}
```

- Full replacement, not patch. `revision` is the exact last observed nonnegative integer; booleans are rejected. `step` is integer 0–5, and completed requires 5.
- `request_key` is 16–120 ASCII letters/digits/underscores/hyphens. Persist and retry the same key and exact semantic body after an uncertain response.
- Success `200` returns the committed GET-shaped snapshot plus `request_key`. Revision advances exactly once. Confirmation time is server-generated for completed only.
- Same key/same canonical body returns the original receipt without rewriting state. Same key/different body or stale revision is `409`. An old successful receipt may be older than current state: clients must not overwrite newer state or another identity/account with it. Read fresh state after ambiguous/stale results.
- Skip-invalidated old draft keys are the exception: `409` instead of replaying discarded choices.
- Unknown fields, enums, duplicates, counts, malformed types, or completed step other than 5 are `422`. No partial writes.
- Arrays are canonicalized in the following order. Order changes alone do not change the request fingerprint.

| Field | Maximum | Allowed values, in canonical order |
| --- | --- | --- |
| roles | 3 | employed, student, independent, business, caregiver |
| apps | 10 | wechat, douyin, xiaohongshu, bilibili, feishu, dingtalk, wecom, mail, calendar, github |
| interests | 5 | technology, career, design, reading, travel, food, fitness, culture, finance |
| reply_detail | one or null | brief, balanced, detailed |
| reply_tone | one or null | natural, warm, direct |

Clients should preserve unsaved choices on a conflict, fetch current state, and let the user resolve the difference. A cancelled HTTP request does not prove that a write failed. No transition based solely on a local optimistic timer.

## Runtime and briefings

`app.py` includes the profile in the existing `service.context_provider` hook. `OnboardingBook.context(task)` resolves the task's identity and exact owner by joining trusted `tasks` and `task_principals`, then reads one validated profile capped at 8 KiB. No principal, draft/skipped, invalid record, or all-empty completed profile yields no profile prompt. The callback cannot select an owner based on model arguments.

Only fixed-label JSON facts are included, with an explicit boundary: preferences are context, not higher-priority instructions, personality judgments, app authorization, recurring consent, or permission to act. The current explicit user request wins. The existing task admission freezes these instructions in the payload; retries reuse the same payload rather than duplicating a model run.

Briefing interests use the same owner's completed profile only while independent briefing preferences have never been saved (`revision == 0`). Any saved preference row, including explicitly empty interests, takes precedence. Fallback changes neither selected sources nor source permissions. Automatic briefing settings still require separate explicit schedule opt-in and freeze the effective preference snapshot at save time; subsequent onboarding edits do not silently change that commitment.

## Export and deletion

Identity export includes `onboarding_profile` as zero or one validated, owner-filtered snapshot. Draft progress is exportable as the user's stored data but is not active model context. Request keys, fingerprints, internal owner scope, and mutation journals are not exported. Invalid/oversized profiles are listed as omitted.

The existing exclusive private-tenant deletion pipeline erases the database with its primary/index/backup roots, including both new tables. A synthetic two-tenant test verifies actual filesystem deletion of these tables in all three areas and preservation of the other tenant. This does not expand production account deletion eligibility; shared-tenant deletion/provider-revocation limitations remain those of the existing account-deletion system.

## Verification

`tests/test_onboarding.py` covers strict enums/types/limits, canonical choices, CAS, concurrent duplicate receipts, identity/owner/tenant separation, draft resumption, skip with late receipts, completed edit cancellation, existing-account prompting, actual App route CSRF/identity/missing-owner behavior, briefing precedence, automatic snapshot freeze, and synthetic private-tenant erasure.

The default-runtime regression calls both `HermesRuntime.prepare_home` and `prepare_profile` for the default and a new identity: both retain `recommend_onboarding=true`. Empty workspaces and generated SOUL/config/profile manifests do not count as user context. Independent tests also verify actual TaskService-to-mock-Hermes payloads for two owners, missing-principal exclusion, trusted task ownership over supplied fields, and owner-bound exports.

Final bounded regression on 2026-10-09: **125 passed in 3.40s**; `git diff --check` passed.

```sh
.venv/bin/python -m pytest -q tests/test_onboarding.py tests/test_onboarding_independent_review.py tests/test_briefings.py tests/test_briefing_preferences.py tests/test_briefing_automation.py tests/test_briefing_automation_review.py tests/test_briefing_automation_export_review.py tests/test_identity_export.py tests/test_identity_export_documents.py tests/test_task_list_data_lifecycle.py
```

The implementation uses local synthetic records and mock model transport in tests. It does not establish provider/model quality, actual first-run retention, or third-party authorization success.
