---
title: Documents and the knowledge base
summary: Writing procedures, manuals and reports; the first revision and later ones, review, approval and publication; confidentiality, sharing, retention and where a document applies.
keywords: [document, documents, rework, raw text, notes, email, e-mail, transcript, minutes, template, templates, variant, rielabora, testo grezzo, procedure, manual, report, knowledge base, revision, draft, submit, review, reject, approval, approve, publish, new revision, edit, retire, confidentiality, riservato, shared, global, retention, markdown, controlled document, attachment, related by meaning, export, pdf, print, download, markdown file, .md, save as pdf]
order: 80
---

The **Knowledge base** holds what is written: procedures, manuals, design and commissioning reports,
drawings, notes. A document is linked to the equipment, types and other documents it applies to.

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

**Documents → Rework from raw text** turns notes, an e-mail, a transcript or an imported page into a draft that
follows the template of a document type. It is also offered from **New document** ("Rework with the template",
for the text you described or the file you added) and on a document's page (**+ Revision from raw text**).

1. Paste the text, or open a file — a PDF, a Word or Excel file, an e-mail, a text file; the file itself is
   attached to the saved draft (*Attach the original file*, ticked by default). Say what it is and, if you know it, when it was
   written. An e-mail's own Date / Inviato line is read first. Tick **The text was written now** only if it was.
2. Choose the document type. The page says which template applies and why: your choice, else your own copy set
   as yours, else the workspace's variant, else the official template.
3. **Preview**: nothing is saved. You see the original (lines used in the draft in green, lines not carried over
   in amber), the draft to edit, and what to check: what is missing (`[da confermare]` in the draft), what was
   deduced (`[da verificare]`), the dates and where each came from, weekdays that do not match their dates,
   lines that read like instructions to an assistant (always treated as text), and records the text names, to
   link if you want.
4. **Save as draft**: a new document, or the document's next revision, in draft. The original text is kept among
   the revision's files, and the page shows the template and the exact version that made it. Submit, approve and
   publish as usual. A procedure, work instruction, safety document or runbook says it is not usable as an
   instruction until it is validated and published. A drawing or manual card points to the original.

The workspace's AI settings apply: confidential (*riservato*) material is sent to the model only where the
workspace allows it. **Draft with AI** and **Review** on the editor are unchanged and work on these drafts too.

## Document templates

**Documents → Templates** lists, for each type, the official template shipped with ARGUS (read-only), the
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
2. **Submit for review**: the revision is locked while it is reviewed.
3. **In review**: someone **other than its author** decides. **Approve**, or **Reject** with a reason: a rejected
   revision goes back to **draft**, with the reason shown, for the author to correct and submit again.
4. **Approved**: **Publish** makes it the revision to work from. Approving does not publish: the two are
   separate steps, and publishing needs the right to approve.

Saving never publishes. A document with no published revision is shown as not published, and is never
presented as something to work from.

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

A file belongs to one revision: the figures a procedure was approved with stay with that revision. Add files to
the **draft**; a published revision's files are not changed. On the phone, the document's **Files** section
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

- **Documents** (by type, status, text and the type's fields), or the search box at the top. On the phone: the **Docs** tab, searched, sorted
  and narrowed to a type.
- **Ask ARGUS** searches documents, tickets, comments and the text of attached files (page by page) by meaning,
  in any language.
- **Related by meaning** on a document lists the equipment, tickets and other documents whose written knowledge
  is about the same thing.
- **Type suggestions** proposes a type for documents that have none.
