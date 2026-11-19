---
title: Documents and the knowledge base
summary: Browsing, writing and importing procedures, manuals and reports; document hierarchy, previews, revisions, review, publication, confidentiality, sharing and retention.
keywords: [view selector, view icons, last view, remembered view, browser preference, list tree board, confluence tables, nested tables, merged cells, native confluence import, document types, hierarchy, folder, preview, subsystem, WP, unfiled, full table, list, tree, board, kanban, review board, bacheca, document, documents, logbook, log, running log, shift log, days, rework, raw text, notes, email, e-mail, transcript, minutes, template, templates, variant, rielabora, testo grezzo, procedure, manual, report, knowledge base, revision, draft, submit, review, reject, approval, approve, publish, new revision, edit, retire, confidentiality, riservato, shared, global, retention, markdown, controlled document, attachment, related by meaning, export, pdf, print, download, markdown file, .md, save as pdf]
order: 80
---

The **Knowledge base** holds what is written: procedures, manuals, design and commissioning reports,
drawings, notes. A document is linked to the equipment, types and other documents it applies to.

## Browse documents before creating another one

**Documents** has three views, selected with **View** near the top right, as on Tickets and Assets:

- **List**: every document in a table, with the type panel, search by title or code, the **Status** filter,
  **Columns**, sorting and bulk operations (copy, move between workspaces, retype, delete).
- **Tree**: folders and parent pages, **Hierarchy** or **Document types**; **Preview** a page or list a
  branch's **Contents**; **+ Folder** and **Move in hierarchy** are here.
- **Board**: documents by where their review stands (see *The review board* below).

**Tools** holds Templates, Rework from raw text, Advanced query and Type suggestions. Search first to avoid
creating a second copy of an existing document.

### Choose a view and return to it

The **View** selector shows icons alongside its text labels. The same selector is used for **Documents**
(**List**, **Tree**, **Board**), **Tickets** (**List**, **Board**) and **Assets** (**List**, **Map**, where the
workspace provides Map). An icon supplements the label; it does not change which views are available.
In Documents, the selector stays on the same row below the header across its three views.

When you return through the main sidebar, each section opens its last visited view. For example, choose
**Documents → Tree**, go to **Cockpit**, then choose **Documents** in the sidebar: Tree opens again. Choosing
Tickets Board does not change the Documents choice.

The preference is kept in this browser, separately for each saved connection profile and section. Workspaces
using that profile share the choice; other browsers or devices do not receive it. Clearing browser storage
removes it. If the browser cannot save preferences, the sidebar uses List as its default. A workspace without
Map opens Assets List even when Map was remembered elsewhere.

A direct link still opens the view, document or revision named in its address. Visiting an explicit view
also makes it the last visited view; a sidebar preference does not redirect that link. The saved preference
remembers the view only, not a selected document, folder or previous filters.

Switching views with the selector retains shared URL filters and starts on the first page. A Tree node or
preview selection is left behind when switching to List or Board. Old bookmarked hierarchy links still open
Tree. **Document types** groups by classification; **Hierarchy** follows parent pages and folders. Neither
switching views nor remembering one changes document content, placement, classification or review state.

## Put a folder under a document

In **Documents → Tree → Hierarchy**, select a parent document and choose **+ Folder**. The **Place under**
selector initially uses that document. Give the folder a name and save. For example, place an **EPIK8s**
folder under **WP04 - Controls**, then create documents inside that folder with **+ New document here**.

To move an existing folder, select it, choose **Edit folder** and change **Place under**. The destination
can be **Top level**, another folder, or a visible document belonging to the current workspace. A folder
cannot be placed under itself or any descendant, including a document inside it. Names must be unique
under the same parent. Moving a folder keeps its contents and updates breadcrumbs and branch counters.

Folder placement is navigation: it does not change document text, revisions, approval state, sharing or
access permissions. A parent document is not an access grant to its children. If a document parent is
unavailable to the reader, the workspace folder is shown at the root without exposing the parent identifier.
Deleting a document parent leaves its folders and their contents at the root; an empty folder is deleted
separately with **Delete empty folder**. Imported parent relationships are not rewritten by these moves.

## The review board

**Documents → Board** shows each document in the column of its newest revision: **Draft**, **In review**,
**Approved**, **Published**. A document whose second revision is a draft sits in Draft, marked *earlier one
published*: readers still see the published one.

Drag a card to the next column, or use the buttons on the card. Each move is the document's own review step,
with the same rules as on the document:

| Move | Means | Who |
|---|---|---|
| Draft → In review | Submit for review | anyone who may edit documents |
| In review → Draft | Withdraw (the author) or Reject, with a reason (an approver) | the author, or an approver |
| In review → Approved | Approve | an approver who did not write the revision |
| Approved → Published | Publish | an approver |

Columns a card cannot go to are dimmed while it is dragged; hover one for the reason. Other moves (Draft
straight to Published, back from Published) do not exist: a published revision is changed by a new revision.
Documents published more than 30 days ago are hidden unless **Published: Any time** is chosen, so years of
logbook entries do not bury the work in progress; **Show retired** adds a Retired column. **Group by** Type or
Owner shows the same cards by type or owner, for viewing only.

Root WP overview pages, folders, imported child pages, icons and counters are explained in *Document hierarchy
and subsystem pages*. In the preview, check **Revision** and the state badge: an open draft can be displayed
before the published version. Use **Open full document** to work on the selected revision.

## Write a document

1. **+ New → Document**.
2. To start from what you already have, paste its text in the side panel or **Add a file** — a PDF, a Word or
   Excel file, an e-mail, a text file — then choose:
   - **Rework with the template** (recommended): the whole text rewritten as a draft that follows the document
     type's template, with what to check (see *Rework from raw text*);
   - **Keep it as it is**: the text becomes the body in Markdown, with the file's structure — a Word file's
     headings, lists, bold and tables; a spreadsheet's sheets as tables; a web page's headings, lists and tables;
     an e-mail's subject, date and message; a PDF's paragraphs put back together, its bullets as lists and its
     headings as headings. The title, type, keywords and a **summary** are suggested and go into the fields
     still empty.

   Either way **the file is attached to the document** when it is saved (untick *Attach the original file* not
   to): the original is never lost, and the body is never replaced by a summary of it.
3. **Title**, **Type** (procedure, manual, report…) and its **Code** (proposed from the type).
4. **Summary**: two sentences on what the document is, apart from the body — shown above it on the document's
   page and found by search. Optional; the assistant suggests one.
5. **Body**, written in Markdown. Attach files (a PDF, a drawing) if the content is there. A Markdown or
   text file (`.md`, `.txt`) attached or dropped on the body asks first: **Use its text as the body** (or
   *Insert its text here*) puts its words in the document; **Attach it as a file** keeps it as a file.
6. **Confidentiality**: *Pubblico*, *Interno*, *Riservato*… A *riservato* document is sent to an AI only if the
   workspace allows it, and is never shared with other workspaces.
7. **Authority level**: whether it is official (*Ufficiale*), informative, or an internal draft.
8. Link it to where it applies (assets, types), and save.

Saving creates the document and its **revision 1, a draft**. On the phone, a document can also start from a
recording or a photo of a page — or take its text from photos with **Text from a photo** — and the recording
(if you ask) or the photos are attached to it; **Tidy with AI** writes rough text up (see *Guided and AI-assisted
entry*).

## Import from Confluence

Use **Workspace → Administration → Imports → New → Confluence** for native Confluence imports, including
Cloud with its supported email/API-token authentication. A saved configuration reads the selected pages and
attachments and can be run again. **New document** no longer has the separate **Import from Confluence —
ELI-NP** panel; ordinary document creation and attachment handling are still available.

Supported complex tables retain nested grids, merged cells, colours and panels as sanitised HTML in the
Markdown body. Review the rendered page, rather than judging that markup as plain text. Cells wrap between
whole words; very wide tables can still scroll. See *Importing data* for source checks, attachment warnings
and re-import limits. An unchanged source version can be skipped: re-running an import does not necessarily
repair an older flattened table. Corrections to an existing published document go through a new editable
draft and the normal review workflow; do not delete the document to refresh its layout.

## Import a web page folder

An HTML page saved with its pictures — a LabVIEW or Doxygen export, a page saved by a browser — is imported from
**New document → Import a web page folder**: **Choose a folder**, or a **.zip** of it. ARGUS lists the pages it
holds, the main one first; tick the ones to import. **Each page becomes a draft document**, with the type,
confidentiality and authority chosen in the form:

- its text as Markdown — headings, paragraphs, lists, tables, bold, code, links;
- **its pictures attached and shown where they were** (a picture used many times is attached once);
- its own HTML attached as the original, and the files it links to (a PDF, a drawing) attached with it;
- a link to another page imported at the same time leads to that page's document.

Tick **Let the assistant suggest each page's type, a summary and keywords** (up to 20 pages at a time) and the
assistant reads each page's text — not its pictures — and proposes them; the type chosen in the form wins, and a
page's own title is kept. Each document says what was suggested: check it there.

The folder's files that no page uses go with the first document: nothing given is lost. Scripts, styles and forms
are left out, nothing is fetched from the internet, and only files inside the folder are read. At most 300 files
and 50 MB. A page that is mostly pictures (a LabVIEW block diagram) is best kept as it is; one with text can then
be reworked with its type's template (**+ Revision from raw text** on its page).

## Rework from raw text

**Documents → Tools → Rework from raw text** turns notes, an e-mail, a transcript or an imported page into a draft that
follows the template of a document type. It is also offered from **New document** ("Rework with the template",
for the text you described or the file you added) and on a document's page (**+ Revision from raw text**).

1. Paste the text, or open a file — a PDF, a Word or Excel file, an e-mail, a text file, or a JPEG, PNG or WebP image. Images are transcribed by the workspace's configured vision model; check the transcription before previewing. The file itself is
   attached to the saved draft (*Attach the original file*, ticked by default). Say what it is and, if you know it, when it was
   written. An e-mail's own Date / Inviato line is read first. Tick **The text was written now** only if it was.
2. Choose the document type. The page says which template applies and why: your choice, else your own copy set
   as yours, else the workspace's variant, else the official template. For a new document, **Share with every
   workspace** can be selected here unless the document is *riservato*.
3. **Preview**: nothing is saved. You see the original (lines used in the draft in green, lines not carried over
   in amber), the draft to edit, and what to check: what is missing (`[da confermare]` in the draft), what was
   deduced (`[da verificare]`), the dates and where each came from, weekdays that do not match their dates,
   lines that read like instructions to an assistant (always treated as text), and records the text names, to
   link if you want.
4. **Save as draft**: a new document, or the document's next revision, in draft. ARGUS opens the new draft revision
   so its text and files can be completed. The original text is kept among
   the revision's files, and the page shows the template and the exact version that made it. Submit, approve and
   publish as usual. A procedure, work instruction, safety document or runbook says it is not usable as an
   instruction until it is validated and published. A drawing or manual card points to the original.

### A log of several days

A running log (a shift log, a machine log) holds many days, each starting with its date on a line of its own
(`26.10.2026`, `2026-10-26`, *Lunedì 26 ottobre 2026*). One draft for all of them is too long to rework well —
the assistant's answer is cut off, or comes back unreadable — and a *Logbook Entry* is one day's record anyway.
When the text holds several days, the page lists them above the text: choose a day and only its text goes in the
box, with its date as **Written or sent on**. Preview and save it as usual: the page stays, marks the day saved
(a link to its draft) and moves to the next day. **Back to the whole text** returns to all of it. The original
file is attached to the first day saved only. What comes before the first day (a title, instructions) is left
out of each day.

The workspace's AI settings apply: confidential (*riservato*) material is sent to the model only where the
workspace allows it. **Draft with AI** and **Review** on the editor are unchanged and work on these drafts too.

## Document templates

**Documents → Tools → Templates** lists, for each type, the official template shipped with ARGUS (read-only), the
workspace's variants and your own copies. **Make a workspace variant** (for those who may approve documents) or
**Make my copy** (for you alone) starts from the official one. In the editor:

- the front matter declares fields and sections; the body uses `{{field:key}}`, `{{section:key}}`,
  `{{meta:title}}`, and `{{#section:key}} … {{/section:key}}` around what is left out when empty. Mistakes are
  shown with their line as you type;
- **Try** runs the draft template on sample text, saving nothing;
- **Publish** makes a new version that never changes. **Use it by default** makes it the one that applies, in
  the workspace or for you;
- **Compare** shows your changes against the official version it came from, and, when ARGUS ships a newer
  official version, what changed in it. Your variant is never updated by itself.

The rules every template follows cannot be changed by a template: nothing invented, sources quoted, a person
approves.

## From draft to published

Every revision, the first one included, goes the same way:

1. **Draft**: open the document and the draft revision; its text is edited in place. **Save** keeps your
   changes; edit and save as often as needed.
2. **Submit for review**: the revision is locked while it is reviewed. Its author can **Withdraw review to edit** before a reviewer decides.
3. **In review**: someone **other than its author** decides. **Approve**, or **Reject** with a reason: a rejected
   revision goes back to **draft**, with the reason shown, for the author to correct and submit again.
4. **Approved**: **Publish** makes it the revision to work from. Approving does not publish: the two are
   separate steps, and publishing needs the right to approve.

Saving a manually created draft never publishes it. A document with no published revision is shown as not
published and is not a released instruction.

Imported Confluence pages are a separate case: the importer records them as published source copies. That
imported state is not evidence that a local author/reviewer approval workflow was completed. Check the source,
authority, scope and revision, and follow your facility's document-control process before operational use.

## Later revisions

Once a revision is published, **+ New revision** starts the next one, a draft copied from the published text.
It follows the same steps: draft → submit → approve or reject → publish. The published revision stays the one
to work from until the new one is published; earlier revisions remain in the history. **+ New revision** appears
only when no other revision is open (draft, in review or approved).

A document replaced by a different document is **retired** and points to its successor (*Replaced by…*).

## Choose the revision to work from

Check the state (published, approved, in review, draft), the authority level, the scope, the equipment it
applies to and any replacement notice. *Ufficiale* does not replace the approval of a controlled revision. A
draft may hold newer information, but it has not been approved.

Link a unit-specific inspection report to that unit; link a general manual at the model or type level. Check
that the document covers the configuration installed before following it.

## Files of a revision

A file belongs to one revision: the figures a procedure was approved with stay with that revision. Use **+ Attach file to draft** to add a file without inserting it into the body, or the editor's paperclip to place an image or link in the text. An in-review or approved revision cannot receive files; withdraw or reject it first. A published revision's files are not changed. On the phone, the document's **Files** section
lists the published revision's files and the draft's, and **Attach to the draft** adds a photo, a video, a
recorded note or a location.

## Export, PDF and print

**Export ▾** on a document, an asset or a ticket gives:

- **Markdown (.md)**: the whole page as a Markdown file — the fields with their names, the body, the steps,
  where it applies and the list of files (each with its link).
- **PDF**: downloads at once an A4 PDF that ARGUS lays out, with the pictures in the text. The file is named
  after the document's code (or the asset's key, or the ticket).
- **Print**: opens the page alone in a new tab, with the print dialog.

On the phone, the export button (**⇪**) at the top of a document, a piece of equipment or a ticket gives
**Open as PDF**, **Print**, **Send PDF** and **Send Markdown** (to mail, Drive, Files…).

A document is exported at the revision on screen; pick another revision first to export that one. An asset's
export lists its relations, tickets and documents; a ticket's, its equipment and comments. What you may not
see — a restricted field, a record of another workspace — is not in the export either.

## Shared documents

A document flagged as **shared** (global) is listed in every workspace, marked *shared from <workspace>*, and
its files open there too. Only its own workspace edits, approves or retires it. A *riservato* document is never
shared.

## Retention

Each document has a retention class: permanent, 10, 5 or 2 years, or none. It is counted from the document's
**last publication**, or its **retirement** if that came later. A released document cannot be deleted before its
retention runs out, only retired. A document never released (only drafts) can be deleted.

## Find what is written

- **Documents → Tree → Hierarchy** shows parent pages and folders. **Document types** groups documents
  by their assigned type: it is a classification, not the parent-page hierarchy. **Documents → List** gives
  the table with type, status and column controls; **Documents → Board** groups documents by review state.
  Switching views does not itself change a document's type, hierarchy or revision state.
  The local title/code search does not search the whole body. **Tools → Advanced query** provides additional
  filters; the search box at the top searches across records. On the phone: the **Docs** tab, searched,
  sorted and narrowed to a type.
- **Ask ARGUS** searches documents, tickets, comments and the text of attached files (page by page) by meaning,
  in any language.
- **Related by meaning** on a document lists the equipment, tickets and other documents whose written knowledge
  is about the same thing.
- **Type suggestions** proposes a type for documents that have none.

## Questions to ask about document navigation and imports

For example, ask **Ask ARGUS**:

- "Where can I see the document hierarchy rather than the document types?"
- "How do I switch between List, Tree and Board?"
- "Why does Documents reopen in Tree, and is that preference shared with my other browser?"
- "Where is the native Confluence import now that its New document panel is gone?"
- "Why does an imported nested table contain HTML in its Markdown body?"
- "Will re-running the import repair a table from an unchanged source page?"

These questions ask for guidance. To change placement, edit a draft, run an import or submit a revision,
use the corresponding ARGUS controls with the required permissions; asking for an explanation does not
perform those actions.
