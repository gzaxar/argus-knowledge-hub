---
title: Workspaces, people and roles
summary: Creating workspaces, adding people, giving roles, groups, API tokens and access reviews.
keywords: [workspace, create workspace, users, people, roles, permissions, admin, administrator, members, groups, access, tokens, keys, access review, grant, revoke, owner, keycloak]
order: 20
---

ARGUS decides who may do what. The sign-in service only says **who you are**; your rights are given in
ARGUS, per workspace, through **roles**. The full reference is `docs/roles.md` in the repository.

## Who can do what

- An **administrator** has installation-wide access: creates workspaces and manages user accounts and
  administrator status.
- A workspace **Owner** can give access to that workspace without being an installation administrator.
- Everyone else gets **roles** in a workspace. A role allows actions (read, create, modify, delete, approve)
  on objects, tickets and documents. A person can hold several roles, and they add up.
- A role can be given to a **group** instead of a person: everyone in the group gets it.

| Role | In short |
|---|---|
| Viewer | sees everything, changes nothing |
| Reporter | sees everything, raises tickets |
| Agent | works the ticket queue |
| Approver | approves and publishes controlled documents |
| Contributor | creates and edits, never deletes |
| Curator | full control of the content, also types, global values and imports |
| Owner | as curator, plus giving access to others |

Domain roles (inventory steward, IT steward, beamline operator, service-desk agent, document controller,
safety investigator, procurement officer, auditor) can be installed from the **Access reviews** page.

## Create a workspace

You need to be an administrator.

1. Open **Administration → Workspaces** and press **New workspace** (or, with no workspace yet, use the form
   on the *Choose a workspace* screen).
2. Type its **Name** (for example *SPARC*). The **Workspace id** is proposed from it, following the rule in
   **Administration → Settings**; it is used in URLs and record keys and **cannot be changed later**.
3. Create it. You are its first member with full rights. Give others access next.

## Give a person or a group a role

1. The person **signs in once**, so ARGUS knows them. (An administrator can also add someone before their
   first sign-in, by email: `argus_admin.py user add <email>`; their first sign-in claims that account.)
2. Open the workspace, then **Access** (**⚙ Workspace** menu, top right). **Granted roles** lists who holds what.
3. **Grant a role**: choose *Person* or *Group*, pick who, pick the **Role**, and grant it. Grant more roles the
   same way: they add up.
4. To take a role away, remove that line from *Granted roles*.

**Members** is the older, per-person way of giving access: *Invite by email* works only for someone who has
signed in once. Prefer roles on **Access**.

People who sign in with the hub's own Keycloak also need a **login there**: an administrator creates it in
Keycloak's admin console (*Users → Add user*, then *Credentials → Set password*, with *Temporary* on so they
choose their own).

## Check every route to access

Removing one role may not remove access: another role, a group, or administrator status may still give it.
Check every route when you review access. **My account** shows the signed-in person's roles; **Access
reviews** gives the whole workspace.

## Make someone an administrator

**Administration → Users**, find the person, and switch **Admin** on. Use it sparingly: an administrator sees
and can change everything. The very first administrators of a new installation are set by whoever runs it
(`ARGUS_BOOTSTRAP_ADMINS`).

## Groups

Groups come from the directory. **Access → Directory** shows where they come from and when they were last
synchronised. Give a role to a group on **Access**, like to a person.

## Tokens for scripts and integrations

- A **personal access token** is for a script acting on your behalf: limited by your roles and the scopes you
  choose.
- A **robot token** is for a machine or service working for a workspace: it belongs to the workspace, so it
  keeps working when people change.

See *My account, API tokens and the mobile app* for creating, using, expiring and revoking them. Whoever runs
the server can also make a robot token from the command line (`tools/argus-admin workspace token <workspace>`):
that one has no expiry and no scope limit, so prefer the **Robot tokens** page, where both are chosen.

The **Keys** page is unrelated to sign-in: it defines how record identifiers such as *SPARC-000123* are made.

## Access reviews

The **Access reviews** page (linked from **Access**) takes a signed snapshot of everyone who has access to the
workspace: people, groups, API tokens, what is open to everyone, and the administrators, with what changed
since the previous review.

1. **Start a review**.
2. Read the changes; remove access that is no longer needed (on **Access**).
3. **Sign** it, with a comment. It is complete once enough different people have signed.

The same page installs the **Roles per domain**.
