---
title: The mobile app (ARGUS Field)
summary: Installing ARGUS Field, signing in, finding equipment by scanning its label, registering units, tickets and documents on the phone, attaching photos, video, notes and places, notifications, working offline, and withdrawing a phone's access.
keywords: [export, pdf, print, share, markdown, mobile, app, phone, android, ios, argus field, field, install, apk, google play, update, sign in, pkce, argus-mobile, scan, qr code, barcode, serial, ocr, read text, nameplate, register, copy from similar, label, attach, photo, video, recorded note, audio, location, where i am, notifications, news, subscribe, offline, outbox, saved copies, cache, settings, dark mode, graph, revoke device, wipe, privacy]
order: 150
---

**ARGUS Field** is ARGUS on Android and iOS, for working next to the machine: find equipment by its label, see
what is installed, report and work tickets, follow procedures, and ask the assistant, also when the network is
poor.

## Install it and keep it up to date

- **From GitHub**: download `argus-field-<version>.apk` from the latest release of the ARGUS repository and open it
  on the phone. When a newer release is published, the app's home screen says so: **Download** gets it, and it
  installs over the one you have.
- **From Google Play**, where your facility distributes it there (internal testing first): Google Play updates it.

The two are signed differently, so a phone keeps one or the other: switching means uninstalling first.

## Sign in

The app signs in like the web app, in the phone's browser, with your organisation's sign-in (OpenID Connect with
PKCE, as the client `argus-mobile`), and registers the phone as a device. It does what your roles allow, no more.
On the Keycloak page, **Google** signs in with a Google account where the installation offers it: the same person
as with Google on the web, recognised by email. With no workspace yet, the app shows none until an administrator
gives you access. The sign-in screen links the **Privacy policy**.

For administrators: the identity provider needs the `argus-mobile` client, with an access token addressed to the
API (an audience mapper adding the web client's id). A new installation's Keycloak has it; an older one adds it
once (`docs/operations.md`, *The mobile app's sign-in client*).

## Find your way around

Six tabs along the bottom, each keeping its place while you use another:

| Tab | What it is for |
|---|---|
| **Home** | search (and **Advanced search**, the icon in the search box), **Scan label**, and the cockpit: open tickets and the counts that need attention, **your tickets in every workspace**, equipment with most open tickets, knowledge health, recent activity |
| **Tickets** | open, yours or all; search; sort by title, creation or change; narrow to a kind |
| **Docs** | documents: search, sort, narrow to a type; which have nothing published yet |
| **Assets** | the workspace's equipment, a page at a time: search by key or name, sort, narrow to a type and the types under it |
| **Graph** | start from equipment, a ticket or a document: what it is connected to, and what is related by meaning |
| **Ask** | the assistant (see *Ask ARGUS*) |

The **menu** (top left) has your account and workspace (**Switch workspace**, **Notifications**, **Unsent changes**,
**Review items**, **Sign out**), **Settings**, **Help** (this guide, in the browser), **About and diagnostics** (the
version, the server, who you are signed in as) and the **Privacy policy**.

A record opens over the tabs; **Back** returns to where you were. Ticket, document and equipment pages show where
their type sits in the type tree (*Equipment › Vacuum › Ion Pump*).

## Scan a label

**Scan label** (Home), then point the camera at the label:

- it reads **QR codes**, **DataMatrix** and **barcodes of every kind** (Code 128, Code 39, Code 93, EAN, UPC, ITF,
  Codabar, PDF417, Aztec);
- **Read printed text (serial, inventory number)** takes a photo of a nameplate and reads it **on the phone**; the
  values that look like a label (the value after *S/N*, *Serial*, *Matricola*, *Inv.*, then codes mixing letters and
  digits, then long numbers) are looked up in turn, and the first record found opens. If none is found, you choose
  what to look up, or register the unit;
- **Or type the label** when the label is damaged or there is no camera.

ARGUS looks the value up as a key, a former key, an alias, a label of any kind, a serial or an inventory number, in
every workspace you can open (see *Equipment*, *Labels and QR codes*). A record of another workspace opens there: the
app moves to that workspace and says so. When several records carry the value, you choose. Only an ARGUS link opens
directly; another web address on a label is looked up as a label, never opened.

## Register equipment

Menu → **Register equipment** (or **Assets → +**, or **Ask → + → Register equipment from a photo**):

1. **Photograph the nameplate**: the values read from it are proposed, each to take or leave.
2. Or **Copy from similar equipment**: scan (or read, or type) the label of a unit like this one; its kind, name,
   manufacturer, model and other attributes are filled in for you to edit. Its serial, inventory number and labels are
   never copied: this unit has its own.
3. **QR code on its label**: scan the new unit's own QR code; it becomes its label.
4. **Check** runs the checks (duplicates included), **Register** creates it, and the nameplate photo is attached.

A unit is never created from a scan alone: you check the values and register.

## On a record

- **Equipment**: what is installed (or where it is installed), connections, open tickets, documents, attributes,
  **Labels** (add one by typing or scanning, remove one), files, comments and history, and **Related by meaning**.
  **Edit** changes its attributes; the change shows in its history.
- **Tickets**: comment, move it through its workflow, edit it, attach files.
- **Documents**: the revision to work from, said before its text (a draft is never presented as something to work
  from); the draft's workflow (**Edit draft**, **Send for review**, **Approve**, **Publish**, **Start a new
  revision**); files; **Related by meaning**.
- **Export** (**⇪** at the top of each of them): **Open as PDF** (in the phone's PDF viewer), **Print**, **Send
  PDF** or **Send Markdown** to mail, Drive, Files or any other app. The same files as Export on the web.

## Attach a photo, video, note or place

**Attach** on a ticket, on equipment, or on a document's draft (**Attach to the draft**) offers:

- **Photo**;
- **Video** (up to 3 minutes);
- **Recorded note**: record, then **Stop and attach**;
- **Where I am**: your position and its accuracy, as a location file. The app asks for the location only when you
  choose this; it never follows you in the background.

Tap an attachment to open it: a photo in the app, a location in the maps app, a video, a note or a PDF in the phone's
own apps. Location data embedded in photos is removed by the server.

## Write documents on the phone

**Docs → New document**, or from a record (**Write a document about it**). **Ask → +** also starts one by voice or from
a photo of a page; **Tidy with AI** writes rough text up (see *Guided and AI-assisted entry*).

**Rework from raw text** (the wand on **Docs**) turns notes, an e-mail, a dictation or a photographed page into a
draft that follows the type's template, as on the web (see *Documents → Rework from raw text*). Paste the text,
say when it was written or that it was written now, pick the type (the template that applies is shown), and
**Preview**: nothing is saved. Then **Draft** to edit, **To check** for what is missing, deduced or contradictory
and the records it names, **Original** for the lines used. **Save as draft** makes a draft that goes through
review as usual. A document started from a photo offers **Rework with the type's template**: the photo goes with
the draft. On a document with nothing open, **From raw text** makes its next revision.

**Dictate a document** (the microphone on **Docs**, or **Ask → + → Write a document by voice**): pick the type,
speak, stop. What you said is transcribed by the workspace's speech model and written up at once with the type's
template, for you to review in **Draft** and **To check** before saving. **Dictate more** adds to it. The transcript
is kept with the draft as its source; the recording too only if you tick **Also keep the recording with the
draft** (off by default). A dictation counts as written now: confirm the date before saving. Check names, codes
and numbers in what was heard.

## Notifications

**Settings → Notifications**:

- for each workspace you can open, **New tickets**, **New and published documents**, **New equipment** (off until you
  choose them), besides the tickets you reported, are assigned or watch;
- **Show news on this phone**: the app checks for news about every 15 minutes while closed on Android, and when the
  system allows on iOS, and shows each as a phone notification; tapping it opens what it is about. Turning it on asks
  the phone's permission; news from before is not shown again.

The bell on **Home** lists your notifications from every workspace, each with the workspace it is from; tapping one
opens it there. **Follow** (the bell icon on a piece of equipment's or a document's page) tells you of each change to
it. While the app is open it checks every couple of minutes. You are never told about what you did yourself, nor
about what you may not read. Until **Show news on this phone** is on, Home offers it.

## Working offline

- Records you open are kept on the phone, **encrypted**, and shown when ARGUS cannot be reached, marked as a saved
  copy. A copy older than 7 days is no longer shown, and is removed.
- What you just saw is shown again for 45 seconds without asking ARGUS (switching tabs, going back); a change you make
  is always followed by the fresh record. Pull a list down to refresh it.
- Changes made offline (tickets, comments, attachments, registrations) wait in **Unsent changes** (menu), encrypted, and
  are sent in order when ARGUS is reachable again. A change is only a fact once ARGUS accepts it; the outbox says if
  one was refused, and why.

**Settings** also has the theme (system, light, dark), **Show keys** (off: equipment and documents by name and title
only) and **Remove saved copies** (unsent changes are kept).

## Signing out, and withdrawing a phone

**Sign out** removes from the phone everything ARGUS saved: the session, the saved copies and the files waiting to be
sent. If there are unsent changes, the app lists them and asks first.

An administrator, or you, can withdraw a phone by **revoking its device** (or ending your sessions at the identity
provider). The phone is signed out and its saved data removed **the next time it reaches ARGUS**. A phone that stays
offline keeps its encrypted copies until then, and stops showing them after 7 days: revoking is not an instant remote
wipe.
