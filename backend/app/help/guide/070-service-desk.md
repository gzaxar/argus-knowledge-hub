---
title: Service desk (tickets)
summary: Reporting a fault or a request, working tickets through their workflow, the board, watchers, notifications and subscriptions.
keywords: [email, e-mail, digest, review requested, ticket, tickets, issue, fault, incident, request, task, service desk, workflow, status, assignee, priority, board, watcher, notification, notifications, subscribe, subscription, sla, resolution, description]
order: 70
---

A **ticket** is a fault, an incident, a request or a piece of work. It is linked to the equipment it affects
and the documents that help.

## Report a fault or ask for something

1. **+ New → Ticket** (on the phone: the **Tickets** tab → **New ticket**, then scan the equipment it is about).
2. **Title**: one line saying what is wrong ("Ion pump GUNSIP01 current rising").
3. **Type**: an operational incident, a request, a task… The type decides the ticket's workflow.
4. **Description**: what you saw, when, what you already tried. For an incident, say when it happened.
5. **Objects**: *Link an object…* to the equipment affected (the checklist suggests the ones your text names).
   *Link a document…* for a procedure that applies.
6. **Priority** and, if you know it, the **Assignee**. Create the ticket.

## Write a useful description

Include what you observed and the exact alarm message, what you expected, when it happened (with the time
zone), the keys of the equipment involved, the effect on operation, the checks you made and their results,
and any readings or screenshots. Write possible causes as unconfirmed hypotheses.

Example: *"Pump GUNSIP01 showed rising current at 10:15 Europe/Rome on 9 October 2026. The cause is unknown.
A trend screenshot is attached. No intervention has been performed."*

Record when the incident happened separately from when you report it, especially if the equipment has been
replaced since. For a request, say what you need, what is hard today and what it would change. Remove
credentials from attachments.

On the phone you can attach a **photo**, a **video**, a **recorded note** or **where you are** to the ticket.

## Work a ticket

- **Tickets** lists them, filtered by type, state, assignee, text and the type's fields; **Board** shows the same
  tickets in columns by state (drag one to move it on).
- Open a ticket to comment, attach files, link more objects or tickets, and **move it on**: the buttons show
  the moves its workflow allows from where it is, and what each needs (an assignee, a resolution, a comment).
- **Related by meaning** lists other tickets, documents and equipment whose written knowledge is about the same
  thing: an earlier fault fixed the same way, a procedure that applies. Each is a lead to check.
- A state with a time limit (SLA) escalates a ticket that stays in it too long.

## Workflows

**Tickets → Tools → Workflows** (or **⚙ Workspace settings → Ticket workflows**) shows each ticket type's states (open, active, waiting, done), the moves between
them and what a move needs. Tickets of a type with no workflow use the built-in one: *New → In Progress →
Pending → Resolved → Closed*.

## If a ticket cannot move to the next state

Check the moves offered and give what they need: an assignee, a comment or a resolution. Ticket types can
have different workflows. If an action is missing because of your rights, check **My account**.

## Record a useful resolution

Record the confirmed findings, the work done, the equipment involved, the checks that show the result, what
remains to do and the procedure used. Say so when the cause is still unknown: restoring operation and finding
the cause are different outcomes.

Use the same ticket for follow-up on the same problem. Before confirming it resolved, repeat the original task
or the applicable check, and record the result.

## Notifications

You are told about a ticket you **reported**, are **assigned**, **watch**, or are **@mentioned** in: a new
assignment, a move to another state, a comment, and a change to its title, description, priority, due date,
equipment or fields. Watch or stop watching any ticket from its page. You are never told about a ticket you
may not read, nor about what you did yourself.

**Follow** a piece of equipment or a document (the **Follow** button on its page, the bell icon in the app) to
be told of each change to it: an edit, a label, a file, a comment; for a document, a new revision, a review,
an approval, a publication, a retirement. The author of a document follows it from the start.

A revision **sent for review** asks the people who can approve it — the document's owner and whoever may
approve documents in the workspace, never its author — with **Review requested**.

Your notifications come from **every workspace** you can open, whichever workspace you are in: each says
which workspace it is from, and opens there.

You can also ask to hear about **everything new** in a workspace: on the web, **My account → Notifications**
(account menu, top right); in the mobile app, **Settings → Notifications**. For each workspace you can open,
switch on **New tickets**, **New and published documents** or **New equipment**. They are off until you choose
them.

## By e-mail

When the installation has a mail server, your notifications also reach you by e-mail — **each one as it
happens**, unless you choose otherwise in **My account → Notifications**:

- **Once a day, in a digest**: everything since the last one, in one message, in the morning (7:00).
- **Never**: only in the app.
- **What to e-mail**: leave out whole kinds — changes to tickets you watch, overdue items, changes to what you
  follow, what is new in the workspaces you subscribed to. Assignments, mentions and review requests are a kind
  of their own.

Each message links to its page, opened in its workspace. **Send me a test message** checks that mail reaches
you. The app keeps every notification whatever you choose for e-mail.

- On the web, the **bell** at the top lists your notifications.
- On the phone, the bell on **Home** lists them, and **Show news on this phone** (same Settings page, or
  **Turn on** on Home) shows them as phone notifications: while the app is open, every couple of minutes and
  when it comes back to the front; while it is closed, about every 15 minutes on Android, and when the system
  allows on iOS. Tapping one opens what it is about. It is **off** until you turn it on: without it, the
  phone shows nothing outside the app.
- On the phone, **Your tickets** on Home lists your open tickets in every workspace: assigned to you, reported
  by you, watched.

## On the equipment's side

An asset's page lists its tickets, and a ticket is counted on the unit that was installed when the incident
happened, so a swapped unit keeps its own history.
