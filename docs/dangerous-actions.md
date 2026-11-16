# Dangerous actions

A few actions reach a whole workspace and cannot be taken back. They are confirmed twice, by a person, with the
workspace's name typed. No token, script or MCP client can do them.

| action | endpoint | when it is dangerous |
|---|---|---|
| delete a workspace | `DELETE /v1/workspaces/{id}` | always |
| make a workspace global | `PUT /v1/workspaces/{id}` | when `is_global` turns on (turning it off is not) |
| delete a type with its records | `DELETE /v1/schemas/{uid}` | always |
| delete the orphaned objects | `POST /v1/workspaces/{id}/cleanup` | when `delete_orphaned_objects` is set |

## What the server checks (`backend/app/services/dangerous.py`)

1. **A person signed in.** A request made with an API token is refused with 403 and the code `person_only`. That
   covers robot tokens and personal tokens, even an administrator's token with the `admin` scope. MCP clients use
   tokens, so MCP cannot do these actions. The MCP tools only read, and the Ask proposals (create, update, relate,
   unrelate, ticket, document) include none of them.
2. **The workspace's name, typed.** The request carries the name in the `X-Confirm-Workspace` header,
   percent-encoded because a header is plain ASCII. It is compared with the workspace's name, with surrounding
   spaces trimmed. When the header is missing or the name differs, the request is refused with 428 and the code
   `confirm_workspace_name`; the response's `workspace` field gives the expected name. For a type, the workspace is
   the one the type belongs to (`X-Workspace-Id`).

Other refusals come first: someone who is not an administrator gets 403, and the catalogue workspace gets 409.

## Removing a person from ARGUS

`DELETE /v1/admin/users/{id}` (`backend/app/services/user_removal.py`), by an administrator signed in only (403
`person_only` with any token), with the person's e-mail address typed in `X-Confirm-User` (percent-encoded; case
and surrounding spaces do not matter; otherwise 428 `confirm_user_email`, with the expected `email`).
`GET /v1/admin/users/{id}/removal` is the preview: what changes, what stays, and `blocked` when it may not be done
(already removed, oneself, the last administrator; the removal itself then answers 409).

Removing is not deleting: the row stays (`removed_at`, `removed_by`, `active` false), so what the person did keeps
their name. What goes:

- signing in: refused with 403 `account_removed` from any identity provider; their personal tokens are revoked, so
  MCP clients using them stop too;
- every role bound to them, the older memberships, site and group administration, installation administration;
- their place in local groups and groups by e-mail domain (a directory group keeps them; they cannot sign in);
- open tickets assigned to them (unassigned), planned activities they own or are given (released), their
  subscriptions, watches and notification settings.

What stays: documents they own, robot tokens they made (they belong to their workspace), their name in history.
Every change is in the access log (`person.removed`, `role.revoked`, `group.member_removed`).

## In the web application

`askTyped(question, name)` (`webapp/src/lib/dialogs.tsx`) asks twice:

1. the question, in red ("Yes, go ahead");
2. "To confirm, type the workspace's name". The button stays disabled, and Enter does nothing, until the name
   matches.

The API client sends the typed name with `confirmHeader(name)`.

`askTyped(question, name, what, same)` asks for something else typed when `what` says so: the Users page asks for
the person's e-mail address, compared without regard to case.

Tests: `backend/tests/test_dangerous_actions.py`, `backend/tests/test_user_removal_domain_groups.py`,
`webapp/src/__tests__/dangerous-confirm.test.tsx`, `webapp/src/__tests__/user-removal-domains.test.tsx`.
