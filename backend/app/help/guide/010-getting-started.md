---
title: Getting started
summary: What ARGUS is, signing in, choosing a workspace and finding your way around, on the web and on the phone.
keywords: [start, sign in, login, keycloak, google, workspace, navigation, search, cockpit, first steps, phone, mobile, app, argus field, privacy]
order: 10
---

ARGUS Knowledge Hub keeps, in one place, an accelerator's **equipment** (assets), the **work** done on it
(tickets) and what is **written** about it (documents), linked to each other. Every asset shows its tickets
and the documents that apply to it; every ticket shows its equipment and the procedures that cover it;
every document shows where it applies.

## Follow a problem from equipment to solution

An ion pump shows an unexpected current rise:

1. Find its record in **Assets** (or scan its label with the phone) and check the unit and its position.
2. Read its existing tickets to see whether the problem has happened before.
3. Open the documents that apply and check their revision and scope.
4. Create a ticket for the new incident, linking the affected equipment and the relevant procedure.
5. Record the investigation, the work performed and the result in the ticket.

The asset identifies the equipment, the ticket records what happened, and the document gives the
instructions or the background. **Related by meaning** on each of them also shows what is written about the
same thing elsewhere, even where nobody linked it (see *The knowledge graph*).

## Signing in

Open the hub's address in a browser (in production, **https://argus-hub.90.147.174.30.myip.cloud.infn.it**).

Choose how to sign in:

- **Keycloak login** (or *INFN login*): your account in the hub's sign-in service. Its page may also offer
  Google, for a Google account.
- **Sign in with Google**: a Google account.
- **API token**: for scripts and tools, not for people.

If it is your first time, an administrator may still have to give you access (see *Workspaces, people and
roles*). You are recognised by your **email**, so sign in with the account whose email the administrator
used. Two accounts with different emails (an INFN and a Gmail address) are two different people in ARGUS,
each with their own access.

On the phone, **ARGUS Field** signs in with the same account (see *The mobile app (ARGUS Field)*).

## Choosing a workspace

A **workspace** is one area of work, usually one machine or facility (SPARC, BTF, ELI…). Start by checking
the workspace you are in. Shared catalogue types and records flagged as shared can also appear from other
workspaces.

- With access to one workspace, you go straight into it.
- With several, choose one on the **Choose a workspace** screen. Switch later from the workspace name at the
  top left of the side bar (on the phone: menu → **Switch workspace**).
- With none, the screen says so. An administrator with no workspace yet gets a **Create workspace** form there
  instead: type a name (for example *SPARC*) and press **Create workspace**.

## If you cannot find your workspace

Open **My account** and check your email and workspace roles. An INFN address and a Gmail address are
different accounts in ARGUS, even if both belong to you.

If the expected workspace is missing, give its administrator the email shown in My account and the workspace
name. Signing in identifies you; it does not by itself give access to a workspace.

## Finding your way around

The side bar holds the main areas, always in the same order (on a phone or a tablet, **☰** at the top left opens
it):

| Area | What it is for |
|---|---|
| **Cockpit** | what needs attention now: open and unassigned tickets, overdue activities, reviews and approvals |
| **Assets** | the equipment: browse by type, search, filter by fields; the **Map** view; **Tools**: advanced query, spreadsheet import, labels and QR codes, bulk changes, imports' mapping |
| **Tickets** | the service desk: the list and the **Board** view, by type, state and assignee; **Tools**: advanced query, workflows |
| **Documents** | the knowledge base: by type and status; templates, **Rework from raw text**; **Tools**: advanced query, type suggestions |
| **Activities** | planned and recurring work |
| **Map** | records with a location, on the map |
| **Knowledge graph** | how records are connected; what depends on what; what is about the same thing |
| **Beam model** | the machine's beam-transport model, linked to its equipment |
| **Ask ARGUS** | ask questions in your own words; it can also propose changes for you to apply |
| **Review queue** | facts that wait for a person: inferred values, proposals, conflicts, installations |

On the Assets, Tickets and Documents pages, the **type panel** beside the results lists the types with how many
records each holds; choose one to see its records (and those of the types below it), **Clear** to see all again,
and *type settings* to change the type. On a narrow screen it opens from the **Type** button above the results.
Tick rows to act on them: the bar of actions (copy, move, delete, change type) appears with the first tick.
**Columns** chooses what a list shows; the filters stay in the page's address, so **List**, **Board** and **Map**
show the same records.

At the top right: **Help** (this guide); **⚙ Workspace settings**: **Access** (who has which role), **Members**,
**Packages**, the **Type catalogue**, **Global values**, **Ticket workflows**, **Equipment classes**, **Keys** (how
record keys are made) and **Administration** (imports, GLPI, icon library, transfer, migration from Jira, AI
endpoint, robot tokens; and workspaces, users, settings and portability for administrators); your name, for **My
account**, **About ARGUS** and **Sign out**.

**+ New** (top right) creates a ticket, an asset, a document or a beam model.

**Search everything** with the box at the top, or **Ctrl K** (⌘ K on a Mac): it covers assets, tickets and
documents at once.

## Getting help

- This **Help** page: search it, or open a topic from the list.
- **Ask ARGUS**: ask "how do I…?" and it answers from this guide, step by step, and from your workspace's own
  records.
- **Privacy**: how ARGUS and its mobile app use data is at
  **https://argus-hub.90.147.174.30.myip.cloud.infn.it/privacy.html** (linked from the app's sign-in screen and
  menu).
