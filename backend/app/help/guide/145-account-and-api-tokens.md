---
title: My account, API tokens and the mobile app
summary: Seeing who you are to ARGUS and what you may do; personal access tokens for your scripts; robot tokens for machines such as a facility's daily-logbook uploader; and where the mobile app is described.
keywords: [olog, phoebus, epik8s, elog, electronic logbook, logbook entry, account, profile, me, who am i, permissions, roles, groups, token, api token, personal access token, pat, robot, robot token, service account, bot, logbook, daily logbook, upload, script, curl, api, automation, scope, expiry, revoke, mobile, app, android, ios, flutter, field, pkce, argus-mobile, mcp, librechat, assistant, ai assistant, claude, list_workspaces]
order: 145
---

## My account

**My account** (top bar) shows who you are to ARGUS:
- the account: name, email, ARGUS id, whether you are an administrator, where the account comes from;
- this sign-in: the identity provider, the client, when you signed in and when the session expires, and
  your realm roles;
- your groups;
- each workspace you can reach, the roles you hold there (directly or through a group) and what they let
  you do on equipment, tickets and documents.

When something answers "not permitted", this page tells you why.

## Personal access tokens

A personal access token lets your own scripts and tools call the API **as you**.

1. On **My account → Personal access tokens**, give it a name (what it is for).
2. Choose what it may do: start from **Read only** or **Read and write**, or tick the scopes yourself.
   Optionally limit it to equipment, tickets or documents, and fix it to one workspace.
3. Choose when it expires (at most a year), and press **Generate token**.
4. **Copy it now**: it is shown only once. ARGUS keeps only a fingerprint of it.

Use it as `Authorization: Bearer argus_pat_…`, with `X-Workspace-Id: <workspace>` unless the token is
fixed to one workspace. It never does more than your own roles allow, whatever was ticked. An
administrator's token carries administrator rights only if the *Administer* scope was ticked; without it,
it reaches only the workspaces where the administrator holds a role. A token
cannot make other tokens: that needs you, signed in.

Revoke a token from the same list as soon as it is not needed or may have leaked.

## Robot tokens

A robot token is for a **machine** that works for a workspace: a control room's daily-logbook uploader,
a data feed, an instrument, the Accelerator Model Toolbox. It belongs to the workspace, not to a person,
so it keeps working when people change. The history names it as `robot:<name>`.

A workspace owner (or an administrator) makes them:

1. Open the workspace's administration → **Robot tokens**.
2. Choose a preset (**Daily logbook upload**, *Read only*, *Data feed (read and write)*) or tick the
   scopes and kinds of record yourself.
3. Choose its lifetime (up to 2 years; *Never* is possible, but a token that never expires is one
   nobody remembers to rotate). Press **Generate robot token** and copy it into the machine's secret
   store.

Give each machine its own token, so one can be revoked without stopping the others. A robot token needs
no `X-Workspace-Id` header.

## Use ARGUS from an AI assistant (MCP)

ARGUS is an MCP server at `<api>/mcp` (transport *streamable HTTP*), so an assistant such as LibreChat or
Claude can look up equipment, tickets, documents and the knowledge graph. Give it a **personal access token
with the read scope** — the assistant then sees exactly what you may see, and can change nothing — and the
workspace to ask in as `X-Workspace-Id` (not needed if the token is fixed to one workspace).

A token that is not fixed to a workspace can ask in **every workspace where you hold a role**: the
`list_workspaces` tool lists them, and every tool takes an optional `workspace` to ask in another one for
that call. A workspace where you hold no role is refused; a robot token, or a personal token fixed to one
workspace, stays in its own. Such a token may also leave `X-Workspace-Id` out and name the `workspace` on
every call instead.

To let the ARGUS MCP server (the control-room assistant) read **every** workspace, an administrator makes a
personal token with the **Read** and **Administer** scopes, not fixed to a workspace, and gives it to that
server as `KNOWLEDGE_HUB_TOKEN`. `list_workspaces` then lists all of them, including those where the
administrator holds no role, and restricted records are visible to it — keep it where the server's other
secrets are kept. Without the *Administer* scope, the same administrator's token reaches only their own
workspaces.

## If an API request is refused

Check the token's expiry, whether it was revoked, its scopes and kinds of record, and the workspace it names (or the
`X-Workspace-Id` header). A personal token also stops at what its owner's roles allow today. `<api>/docs` describes
every request and its answer.

## Upload a facility's daily logbook

With a **Daily logbook upload** token (read, create and modify documents), a nightly job:

1. creates the day's entry: `POST /v1/documents` with a uid such as `logbook-<facility>-<date>`, the
   title, the workspace's *Logbook Entry* type, and the summary as `body_markdown`;
2. attaches the full logbook file: `POST /v1/documents/<uid>/revisions/<uid>-r1/attachments` (multipart,
   field `file`).

The **Robot tokens** page shows the exact commands, with this workspace's logbook type filled in.
Re-running the same day's creation answers 409 (already there). If a run stopped half way, check the two steps
apart: the first run may have created the document without attaching the file. Attach it to the day's draft
revision (`<uid>-r1`); attaching the same file twice adds a second copy, and a revision already published takes no
new files. Logbooks are then indexed like every other document, and Ask ARGUS can answer "what happened last
Tuesday on the linac".

The same pattern serves any other data: a token with only the scopes and kinds of record the job
needs, and the endpoints listed in the API reference at `<api>/docs`.

## Facility logbooks from Olog

A facility running the EPIK8s Olog service can send **every logbook entry** here once a day. Each entry
becomes a *Logbook Entry* document of the facility's workspace (code `OLOG-<FACILITY>-<id>`), published,
with its logbooks, tags, level, properties and files, a link back to Olog, and relations to the equipment
it names. An entry edited in Olog becomes a new revision; one unchanged is left alone.

To set it up for a facility:

1. In ARGUS, on the workspace's **Robot tokens** page, generate a **Daily logbook upload** token.
2. On the facility's cluster, store it once:
   `kubectl -n <facility> create secret generic argus-olog-upload --from-literal=token=argus_bot_…`
3. In the facility's EPIK8s `deploy/values.yaml`, under the `olog` service, set `argusUpload` (`enabled`,
   the ARGUS API `url`, `facility`, and `entryUrl` for the links back to Olog).
4. For the first run, send the logbook's history (`all: true`, or a job started by hand with
   `OLOG_ALL=true`); after that, the job runs nightly and sends the last two days.

The job is `tools/olog-to-argus` in the ARGUS repository, run by the Phoebus services chart.

## API tokens (administrators)

**Administration → API tokens** lists every personal and robot token in the installation: who made it,
what it may do, when it expires, and when it was last used. An administrator can revoke any of them.

## The mobile app (ARGUS Field)

The Android and iOS app does **not** use tokens typed into it: it signs in like the web app, through the phone's
browser, with the identity provider, and works with the person's own roles. How to use it, how it signs in and how
its access is withdrawn are in *The mobile app (ARGUS Field)*.
