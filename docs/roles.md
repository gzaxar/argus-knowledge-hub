# Who may do what: administrators, roles and groups

ARGUS decides access itself. The identity provider (the temporary Keycloak, Google, later INFN's own)
only says who someone is: ARGUS reads the token's subject, email and name, and nothing about roles or
groups. Everything a person may do is held in ARGUS and granted there.

## The pieces

| | What it is | Where it is set |
|---|---|---|
| **Administrator** | A flag on a person: everything, in every workspace, plus creating workspaces and managing people | `ARGUS_BOOTSTRAP_ADMINS` for the first ones; then *Administration → Users*, or `argus_admin.py user admin <email> on` |
| **Role** | A named set of permissions | built in (below), or a template installed in the workspace |
| **Grant** (role binding) | A role given to a person **or a group** in **one workspace** | the workspace's *Members* page, `tools/argus-admin grant`, or `POST /v1/workspaces/{id}/bindings` |
| **Group** | People granted together; synchronised from the directory | the workspace's *Access* page, *Directory* (`POST /v1/directory/sync`) |
| **Workspace defaults** | What anyone signed in may do in a workspace where they hold no grant at all | the workspace's settings (`default_can_…`) |

A person can hold **several roles**, in the same workspace and in different ones: owner of SPARC and
viewer of BTF, or both reporter and approver in SPARC. Their permissions add up, with those of every
group they are in; a role never takes anything away. The same role cannot be granted twice to the
same person in the same workspace.

## What a permission is

A role gives **actions** on **resources**:

| Resource | Actions |
|---|---|
| `objects` (equipment, places, the catalogue) | read, create, modify, delete, approve |
| `tickets` | read, create, modify, delete, approve |
| `documents` | read, create, modify, delete, approve |
| `workspace` | manage_members (grant and revoke roles here) |
| `restricted` | the restricted classes it may see: ARGUS's `costs`, `personnel`, `security_incident`, `safety_investigation`, `sensitive_design`, and those the template packages declare (`commercial_terms`, `unpublished_invention`, `source_security`, `physical_security`, `license_keys`) |

A record or field of a restricted class is invisible to anyone without that class, even with `read`:
it is left out of lists, search, the graph (or shown only as an anonymous node) and Ask ARGUS's answers.

## The built-in roles

Present in every instance (`tools/argus-admin role list`), and kept current by each release.

| Role | Objects | Tickets | Documents | Also |
|---|---|---|---|---|
| `viewer` | read | read | read | |
| `reporter` | read | read, create | read | raises tickets |
| `agent` | read | read, create, modify | read | works the ticket queue |
| `approver` | read | read | read, approve | approves and publishes controlled documents |
| `contributor` | read, create, modify | read, create, modify | read, create, modify | never deletes |
| `curator` | all but approve | all but approve | all but approve | types, global values and imports |
| `owner` | all but approve | all but approve | all | grants and revokes roles in the workspace |

## Domain roles (templates)

Roles shaped for the people who look after one part of the machine. They are ordinary roles once
installed, with ids `argus-<name>`: install them on the *Access reviews* page (from the workspace's
*Access* page), or `POST /v1/access-reviews/templates`.

| Role | For | Objects | Tickets | Documents | Restricted classes |
|---|---|---|---|---|---|
| `argus-inventory-steward` | equipment, locations and the catalogue; merges and bulk changes | all | read, create | read | |
| `argus-it-steward` | IT equipment, ports, addressing and IT installations | all | read, create | read | |
| `argus-beamline-operator` | a beamline's positions and installations; reports faults | read, modify | read, create, modify | read | |
| `argus-service-desk-agent` | works tickets through their workflows | read | read, create, modify, approve | read | |
| `argus-document-controller` | reviews, approves and releases controlled documents | read | read | all | |
| `argus-safety-investigator` | safety and security investigations | read | read, create, modify | read | `safety_investigation`, `security_incident` |
| `argus-procurement-officer` | costs and procurement records | read, modify | read | read | `costs` |
| `argus-auditor` | reads everything, changes nothing; verifies the audit log | read | read | read | |

The template packages recommend roles of their own (a fire safety officer, a radiation protection expert, a
contract manager, a technology transfer officer, a change manager…). A workspace is offered those of the
packages it has, beside the ones above, with the package each comes from; installing them grants nothing.
docs/domain-packages.md lists them, and the decisions their domain owners must take about them.

## How access is worked out

For a person, an action and a resource in a workspace, in order:

1. **A workspace being imported** (portability staging) is closed to everyone until it is finalized; an
   evidence import is read-only.
2. **An administrator** may.
3. **The person's grants** are added together: roles given to them, roles given to any group they are
   in, and the per-person flags of workspaces created before roles existed. If any of them has the
   action, they may. Grants only add; nothing subtracts.
4. **Held something here, but not this:** no. A viewer is not given `create` by an open workspace.
5. **Held nothing here at all:** the workspace's defaults decide. They are all off unless set.

Who may grant: an administrator, or someone with `manage_members` on that workspace (an owner).
Installing the templates and running access reviews needs `approve` on objects (an administrator, or
an inventory or IT steward).

**API tokens** belong to one workspace and act there with full rights, seeing only the restricted
classes they were given. They have no person behind them, so they cannot create workspaces or manage
people.

## Common tasks

In the cluster, run `argus_admin.py` in the API pod
(`kubectl --kubeconfig ~/kubeconfigs/cloud-config.txt -n argus exec deploy/argus-api -- python scripts/argus_admin.py …`);
locally, `tools/argus-admin …`.

```bash
argus_admin.py user add mario.rossi@lnf.infn.it --name "Mario Rossi"   # before their first sign-in
argus_admin.py grant mario.rossi@lnf.infn.it contributor sparc
argus_admin.py revoke mario.rossi@lnf.infn.it contributor sparc
argus_admin.py access mario.rossi@lnf.infn.it                           # what they hold, and where
argus_admin.py user admin mario.rossi@lnf.infn.it on                    # administrator
```

A person is known by email: added before they ever sign in, their first sign-in with that email
claims the same account, grants included. With the temporary Keycloak they also need a login there
(its admin console, *Users*); with INFN's identity provider they already have one.

`GET /v1/workspaces/{id}/my-permissions` shows what the signed-in person may do in a workspace, which
is what the web app uses to show or hide actions.

## Access reviews

An access review is a signed snapshot of every grant in a workspace: people (directly and through
groups), groups, API tokens, the workspace defaults and the administrators, with what changed since the
previous review. The *Access reviews* page, or `/v1/access-reviews`:

1. **Start** one (`POST /v1/access-reviews`); it records the snapshot and its hash.
2. **Look** at what changed since the last one.
3. **Sign** it (`POST /v1/access-reviews/{id}/sign`). It is complete once enough distinct people have
   signed. It is never edited afterwards.

## Further

- [`oidc-dev-setup.md`](oidc-dev-setup.md): the local Keycloak, its six test users and the permission
  model they exercise.
- [`../k8s/README.md`](../k8s/README.md): the first administrators in production
  (`ARGUS_BOOTSTRAP_ADMINS`).
- The code: `backend/app/services/roles.py` (built-in roles), `backend/app/services/access_review.py`
  (templates and reviews), `backend/app/services/permissions.py` (how access is worked out),
  `backend/app/services/visibility.py` (restricted classes).
