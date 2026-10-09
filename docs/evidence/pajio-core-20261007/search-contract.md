# Native cross-object search

## Mounting

In the existing authenticated application boundary:

```python
from .search import SearchBook
from .search_api import install_search_routes
install_search_routes(app, SearchBook(store))
```

Identity always comes from `request.state.identity_id`; this module accepts no body-selected identity. The existing Gateway and tenant boundary continue to authenticate requests. The native client sends `connectionHeaders(connection)` including Bearer and expected tenant, plus `X-Wearing-Identity`, and rejects foreign identity responses.

```tsx
<NativeSearchPanel
  connection={connection}
  onTask={openExactTask}
  onRecord={openExactLifeRecord}
  onFiles={query => openWorkspaceWithQuery(query)}
  onBack={closeSearch}
/>
```

`onMessage` is optional. Without it, a chat hit opens the exact user message and its saved reply natively, with a button to the exact underlying task. The parent must not pretend that opening the general chat page locates a specific message. The panel fits the existing native scroll container and uses current theme tokens.

## API

`GET /api/search?q=旅行&kind=all&limit=20&cursor=...`

- `q`: 1–120 Unicode characters after trimming; literal substring, case insensitive; control characters rejected.
- `kind`: `all`, `task`, `record`, `message`.
- `limit`: 1–50, default 20.
- `cursor`: optional opaque, signed, at most 2048 characters.
- Response: `identity_id`, `query`, `kind`, `as_of`, `files_included:false`, `items`, `next_cursor`.
- Item: `key`, `id`, `kind`, `title` (up to 100 characters), `snippet` (up to 212), `matched_field` (`title/content/output`), `record_kind`, timestamps and a typed `target`.
- Targets: `{kind:'task',task_id}`, `{kind:'record',record_id}`, `{kind:'message',task_id,message_id}`. No arbitrary URL or client-generated path.

`GET /api/search/messages/{message_id}` returns only the owned message `id`, `task_id`, `content`, saved `output`, `status`, and timestamps, plus `identity_id`. Missing/foreign messages are 404. It does not expose run/session IDs, request payloads, errors, tokens or idempotency keys.

## Search scope and pagination

Search reads the full selected identity's database on the server, not a client-side 200-row cache. Existing Store has no FTS index. This first implementation performs a parameter-bound literal search over task title/prompt/output, message text/reply, and nondeleted life-record title/content. It does not search task payloads, internal errors, runtime logs, file paths or file contents. In `all`, conversation turns are shown once as chat hits; explicit `task` search includes their execution tasks too.

Results use stable keyset ordering (`created_at DESC`, typed `key ASC`). The cursor binds identity, exact query, type, first-page time, position and a 15-minute expiry. Results inserted or updated after first-page time are deferred until refresh; deleted results disappear. This is not an immutable content snapshot. Replaying an unchanged cursor over an unchanged corpus returns the same page. Wrong identity/query/type, tampering, expiry or process restart returns 409 and the native page offers a fresh search.

The default SQL execution budget is 1.5 seconds. Exhaustion returns a visible 503 asking for a more specific term/type; it never returns a false empty/success response. Response page size is bounded and no total-count estimate is presented. At substantially larger corpus sizes an indexed search implementation is still needed; this endpoint does not claim a scalable semantic/FTS service.

Native query/filter changes abort and invalidate the prior request. Identity changes remount the session. Pagination errors preserve the current results and retry the same cursor; an expired cursor explicitly restarts. Details validate both message ID and task ID before rendering plain selectable text. File search opens the separate WorkspacePager surface, described as **file-name search**, without a claim that file正文 is indexed.

## Validation

Backend tests cover 257 matches over 17-item pages, same-time ordering, repeat cursors, cross-identity refusal, query/type/signature/expiry/restart refusal, new insertions/edits, deleted rows, literal punctuation, internal-field exclusion, visible budget errors, and authenticated HTTP contracts.

Native protocol tests cover exact typed deep links, foreign/malformed responses, query bounds, Bearer/expected-tenant/identity headers, URL credential exclusion, no retry loop on conflicts, and continuation deduplication. Device interaction acceptance remains a separate root task.
