# Quotas

What a workspace may hold and use, set in **Administration → Quotas** (`backend/app/services/quotas.py`,
`backend/app/routers/quotas.py`). The user guide is in the app's help (*Administration → Quotas*); this is how it
works.

## Settings

One app setting, `quotas`: `{"defaults": {key: n|null}, "workspaces": {id: {key: n|null}}}`. A key absent from
`defaults` is its built-in default; `null` is unlimited. A key absent from a workspace's own follows the default.
`ARGUS_QUOTA_IMPORTS_AT_ONCE` changes the built-in default of the installation's import quota (empty or
`unlimited`: none; the tests set it).

| Key | Counts | Built in |
|---|---|---|
| `storage_bytes` | `sum(attachments.file_size)` of the workspace | 50 GiB |
| `file_bytes` | one file | 2 GiB |
| `ai_tokens_5h`, `ai_tokens_week` | `quota_ai_usage` (tokens per workspace and hour) over 5 h / 168 h | none |
| `assets`, `documents` | not deleted | none |
| `members` | users with a role binding or a legacy membership (groups are not counted) | none |
| `api_ops_day`, `api_ops_minute` | requests from `api` and `mcp` clients naming the workspace | none |
| `imports_at_once` | portability imports not finalized, discarded or invalid (installation) | 1 |

## Where it is checked

- **A flush guard** (`before_flush`): new `Asset`, `Document`, `Attachment`, `RoleBinding` (user) and `Membership`
  rows, per workspace, against its quotas — only the quotas that have a limit cost a query. It raises
  `QuotaExceeded`, which the API answers as `429 {"detail": {"code": "quota_exceeded", "quota", "limit", "used",
  "adding", "frees_at", "error"}}`. Every path that writes is held to it; edits and deletes add nothing.
- **Uploads**: `POST /v1/uploads` checks the file's size and the room left before a byte moves.
- **The language model**: `llm._post` checks the workspace of the request before each call (`LLMQuotaExceeded`,
  an `LLMError` the callers already show); `usage.note_llm` adds the tokens to the hour, statistics on or off.
- **API operations**: the usage middleware, before authentication, for `api`/`mcp` clients; counted in memory per
  API process (today seeded from the usage counts already written), so with several replicas each counts its own.
  The web app and the Android app are not counted. A refusal carries `Retry-After`.
- **Imports at once**: `portability.service.create_import`.

Not stopped: an instance administrator signed in (auth marks the request; with a token they are), and a
portability import loading an archive (`LOADING_ARCHIVE`) — its dry run lists `quota_warnings` instead.

## Warnings

`status()` gives each quota's ratio and level (`warn` from 80%, `over` at 100%); the workspace's administration
pages show a banner, and `argus_quota_ratio{workspace,quota}` (published hourly and on every look) drives the
`ArgusQuotaNearLimit` alert of the chart's PrometheusRule.
