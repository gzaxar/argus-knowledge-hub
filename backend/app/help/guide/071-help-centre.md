---
title: Help centre (service portal)
summary: Asking a site's services for help and following your requests; answering them as staff; setting up a site's help centre, its services, request types, teams and destinations.
keywords: [help centre, help center, service portal, portal, services, service, request type, request, my requests, helpdesk, service desk, not sure, requester, team, queue, public reply, internal note, publish, authorise, authorize, destination, site, support, emergency]
order: 71
---

Every site can open a **help centre**: people at the site and at its facilities find the right service, send a
request and follow it under **My requests**. Each request is one ordinary ticket in the service's workspace, in
its team's queue; the team works on it from **Tickets** like any other.

## Ask for help

1. Open **Services & Support** in the side bar (or go to `/support`). With one site you land on its help centre;
   with several, choose one.
2. Type what you need in **What do you need help with?**, or pick a category and a service card, then the
   request type that fits (for example "Wi-Fi or network problem").
3. Not sure which service? Use **I'm not sure — ask the service desk**: the site's helpdesk finds the right team.
4. Fill in the form: a one-line **Summary**, the **Details** (what happens, since when, where, what you tried),
   the fields the request type asks for, and attach screenshots or logs.
5. **Review** shows the service, the responsible team, where you report from and exactly what will be sent.
   Then **Send request**. Sending twice (a double click, a lost connection) still makes one request.

In an emergency follow the instructions in the red band at the top of every page, not the portal.

## Follow my requests

**My requests** lists your requests at the site, with their status — Open, In progress, Waiting, Resolved — and
a **New reply** mark when the team has answered. Open one to read the team's replies and files, add a reply or a
file, and **Reopen request** if it was resolved but the problem is back. You are told by e-mail too, as your
notification settings say (**My account**).

You see what you sent, the team's public replies and the files shared with you: never the team's internal notes.
Only you see your requests.

## Answer requests (staff)

A request is a ticket in your workspace: find it under **Tickets**, filtered by **Service** and **Team**, or on
the board. On the ticket:

- the **Service request** panel shows who asked, from which facility, and under which service and request type;
  change the **Service** or the **Team queue** there to move it within your workspace (the history keeps it);
- choose **Internal note** (only staff see it — the default) or **Public reply** (the requester reads it) before
  writing; public replies have a blue mark, notes an amber one;
- a file is internal until you choose **Share with requester** beside it;
- move it through its workflow as usual: the requester sees the status change, and is told when it is resolved.

The team is a queue, not the assignee: assign the ticket to a person as usual. Being in the team gives no rights:
its members work under their roles in the workspace.

## Set up a site's help centre

For a site administrator (or an installation administrator), in **Administration**, section of the site, **Help
centre**:

1. **New service**: its name, category (IT, Facilities…), what it handles, hours and contact; **Tickets go to**
   (the site or one of its facilities) and the **Responsible team** (a group).
2. Under the service, **+ Add** a **request type**: its name and description, the guidance shown above the form,
   the **Ticket type** its tickets get, and the **Fields the requester fills in** (only those are asked and
   accepted; the type's other fields stay internal). Tick **required** where needed.
3. **Publish** the service. It takes requests only when its destination is authorised (see below), the team has a
   role that reads and changes tickets in that workspace (for example **Agent**), and its ticket type can be used
   there. What is missing is listed in amber under the service.
4. Create a **Service desk** service with a request type for "I'm not sure", choose it in **"I'm not sure" goes
   to**, add the emergency instructions and the welcome text, tick **Open the help centre to requesters** and
   **Save**. The help centre cannot open without that helpdesk.

**Open the help centre as requesters see it** shows the result; while it is closed only its administrators see it.

## Authorise a destination

A site administrator cannot send tickets into a workspace on their own: someone who manages that workspace's
access (by a role there, such as **Workspace administrator** or **Owner**), or an installation administrator,
authorises each service. They find the services waiting in **Administration → Help centre destinations** and press
**Authorise**; **Revoke** stops a service at once. Someone with both rights authorises it simply by publishing.

If the destination stops being valid — the facility left the site, the team was deactivated or lost its role, the
person who authorised it lost their right — the service stops taking requests and says why: nothing is ever sent
somewhere else without asking.

## Optional help while choosing

With **Offer help while choosing** ticked, typing in the search box also suggests published articles from the
requester's own workspace that they may read. Where that workspace's AI is on, **Ask the assistant which service
fits** suggests a request type and drafts a summary; the requester checks and sends it. Without AI nothing is sent
to a model, and the form always works.
