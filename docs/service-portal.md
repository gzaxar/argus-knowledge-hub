# Service portal

Every site can open a **help centre**: people at the site and at its facilities find the right service, send a
request, and follow it under **My requests**. Each request is one ordinary ARGUS ticket in the service's workspace,
in its team's queue. Staff work on it with the ticket pages, boards and workflows they already use.

The layout follows a familiar customer-portal pattern: a "How can we help?" header with search, service cards
grouped by category with their request types, a form for each request type, a review step, and a request page
with status, public conversation, files and resolution. Administration lives apart, under the site's
administration.

The help centre is a full-screen part of the web app at `/support` (the sites one may use), `/support/<site>`,
`/support/<site>/new/<request type>` (`helpdesk` for "I'm not sure"), `/support/<site>/requests` and
`/support/<site>/requests/<id>`. It has its own header — Services, My requests, the account menu — and none of
ARGUS's own menus; "Open ARGUS" appears only to someone with a workspace to work in. It uses the same sign-in, and
someone signed in who only asks for help is not asked to choose a workspace. Notifications to requesters link
there. The earlier `/sites/<site>/services…` addresses redirect to it.

## Concepts

| Thing | What it is | Where |
|---|---|---|
| Site | A workspace with role `site`; its facilities point to it (docs/sites.md) | `workspaces` |
| Portal settings | Open or not, headline, welcome text, emergency text, the helpdesk request type, assistance | `site_service_settings` |
| Service | An offering ("Network & connectivity"): category, description, hours, contact, **provider workspace**, **team** | `service_offerings` |
| Request type | What a person asks a service for, its guidance, ticket type and requester fields | `service_request_types` |
| Support request | Whose request a ticket is; what they sent; how it was routed | `support_requests` |
| Ticket | The one canonical record, with `service_uid` and `assigned_group_uid` | `issues` |

A team is an existing group. Belonging to it grants nothing: the team works under the ticket rights its roles give
it in the provider workspace. The team is a queue (`assigned_group_uid`); the assignee stays a person.

## Routing

Routing is deterministic: **request type → service → provider workspace + team**. "I'm not sure" is the site's
helpdesk request type. The review step shows the service, the responsible team, where the person reports from and
exactly what is sent; the submission carries the route version that was reviewed, and a different route at
submission time is refused with `409 route_changed` and a fresh preview.

A service takes requests only while:

* its provider workspace is the site or one of its current facilities, and is not being imported;
* its team is an active group whose roles there read and change tickets;
* someone who manages the provider workspace's access by a role of their own there (or an installation
  administrator) has authorised it, and still may;
* its request types' ticket types exist, can be used in that workspace, and the requester fields are fields of the
  type that are neither restricted nor ARGUS's own.

When that stops being true the service is refused with `409 service_unavailable` — never sent elsewhere silently —
and the helpdesk is offered as an explicit choice. Staff can move a request to another service or team of the same
workspace (the history records it, and the new team is told); moving it to another workspace is not done by the
portal.

## Who may do what

| Who | May |
|---|---|
| A person signed in who can read the site or one of its facilities | See the open portal, send requests from a workspace of theirs at the site, follow, reply to, add files to and reopen **their own** requests |
| Site administrators, installation administrators | Manage the catalogue and settings, publish and unpublish services, preview a portal not yet open |
| Whoever manages the provider workspace's access by a role there | Authorise a service into it, or revoke that (Administration → Help centre destinations) |
| Staff with ticket rights in the provider workspace | Work the ticket as any other; choose **Public reply** or **Internal note**; share a file with the requester |

API tokens have no portal access. A requester's ownership is checked on every call, including downloads; a guessed
request or file id answers 404. Losing access to the site and its facilities ends portal access to past requests.

## What a requester sees

What they sent (summary, details, the fields they filled in), public replies, the files shared with them, a status
from the workflow's state **category** (`open` → Open, `active` → In progress, `waiting` → Waiting, `done` →
Resolved) and the resolution. Never internal notes, internal files, history, watchers, other tickets, or the
equipment of their workspace. A ticket in a restricted class the requester may not see shows only its reference,
service and status.

Every comment and file written before the portal is internal (the migration sets `audience = internal`); only an
explicit choice makes a reply or a file public, and changing a file's audience is kept in the ticket's history.

## Notifications

* The team's members who may read tickets in the provider workspace are told of a new request (`queued`), and of a
  request moved to their team.
* The requester is **not** a watcher. They are told of public replies and shared files (`request_reply`) and of a
  change of requester-facing status (`request_status`, `request_resolved`), with a link to the portal page, never
  to the ticket. Their e-mail preferences have a category of their own.
* On a portal ticket, every other notification (comments, mentions, edits, escalations) goes only to people who may
  read tickets in its workspace: mentioning the requester in an internal note tells them nothing.

Notifications are rows written in the same transaction as the ticket and delivered by the existing e-mail job,
which retries; a delivery failure never loses or duplicates a ticket.

## One request, one ticket

The client makes a `submission_uid` once per request and sends it with every retry. `(requester, submission_uid)`
is unique: a retry answers `200` with the request already made, a concurrent duplicate is caught by the constraint,
and the same id with different content answers `422 idempotency_mismatch`. Ticket creation is shared with the
ticket form (`app/services/tickets.py`): the migration guard, the occurrence rule of incidents, field validation,
the workflow's first state, the key, the history and the equipment link are the same.

## Optional assistance

When a site turns assistance on, the search box also suggests **articles**: published, non-confidential documents
of the requester's own workspace that they may read there. On request, and only where that workspace's own AI
configuration is enabled and checked, the assistant suggests one of the request types the person could choose and
drafts a summary; the person reviews, edits and sends it. The model sees only the person's text and the request
types' names and descriptions. With AI off no model call is made, and the manual form is always there.
Cross-workspace knowledge search is not part of the portal.

## API

Requester (`/v1/support`, no `X-Workspace-Id` needed): `GET /sites`, `GET /sites/{site}`,
`GET /sites/{site}/request-types/{uid}`, `POST /sites/{site}/route-preview`, `POST /sites/{site}/requests`
(multipart: `payload` JSON and `files`), `GET /sites/{site}/requests`, `GET /sites/{site}/requests/{uid}`,
`POST .../messages`, `POST .../attachments`, `GET .../attachments/{file}`, `POST .../reopen`,
`POST /sites/{site}/assist`.

Staff: `GET /v1/support/queues` (services and teams of the current workspace), `GET /v1/issues/{uid}/service-request`,
`PUT /v1/issues/{uid}/attachments/{file}/audience`, `audience` on `POST /v1/issues/{uid}/comments` and on
attachment upload, `service_uid` / `assigned_group_uid` filters on `GET /v1/issues` and fields on `PUT`.

Administration (`/v1/admin/sites/{site}/service-desk`): `GET`, `GET /options`, `PUT /settings`, `POST /services`,
`PUT /services/{uid}`, `POST /services/{uid}/authorize|revoke|publish|unpublish`,
`POST /services/{uid}/request-types`, `PUT /request-types/{uid}`; `GET /v1/admin/sites/service-desk/authorizations`.

## Ask ARGUS

Ask ARGUS answers "how do I…" about the help centre from the user guide (`search_help`, `read_help`, topic
`help-centre`) and, when a site administrator asks, proposes a service with `propose_help_centre_service`: site,
destination, team, ticket types and requester fields are resolved and checked when it is proposed, and a wrong
name is refused with the valid choices. Applying it runs the administration API in the name of the person who
confirms, so only a site or installation administrator can; it creates the service as a draft. Publishing,
and authorising the destination, stay manual. MCP clients get the same proposal, reviewed on the Proposals page.

## Portability

The signed portable archive carries the portal: settings, services and request types with the site, support
requests with their tickets, and the requesters among the people. A workspace bundle does not (the catalogue
belongs to the site). References from the portal to workspaces, groups, types and services are checked by the
application rather than by foreign keys, so an archive of one facility loads without its site's catalogue.

## Not in this release

Service-level targets and business calendars, a governed handoff between provider workspaces, external ticket
systems, routing rules beyond the request type (origin facility, equipment ownership), approved help publication
across workspaces, and AI troubleshooting conversations. Existing workflow timers (`sla_hours`) still escalate as
before.
