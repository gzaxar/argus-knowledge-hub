---
title: Documents and the knowledge base
summary: Writing procedures, manuals and reports; the first revision and later ones, review, approval and publication; confidentiality, sharing, retention and where a document applies.
keywords: [document, documents, procedure, manual, report, knowledge base, revision, draft, submit, review, reject, approval, approve, publish, new revision, edit, retire, confidentiality, riservato, shared, global, retention, markdown, controlled document, attachment, related by meaning, export, pdf, print, download, markdown file, .md, save as pdf]
order: 80
---

The **Knowledge base** holds what is written: procedures, manuals, design and commissioning reports,
drawings, notes. A document is linked to the equipment, types and other documents it applies to.

## Write a document

1. **+ New → Document**.
2. **Title**, **Type** (procedure, manual, report…) and its **Code** (proposed from the type).
3. **Body**, written in Markdown. Attach files (a PDF, a drawing) if the content is there. A Markdown or
   text file (`.md`, `.txt`) attached or dropped on the body asks first: **Use its text as the body** (or
   *Insert its text here*) puts its words in the document; **Attach it as a file** keeps it as a file. The same
   choice appears when such a file is given to *Describe it*: **Use the file as the body** instead of the
   summary the assistant writes.
4. **Confidentiality**: *Pubblico*, *Interno*, *Riservato*… A *riservato* document is sent to an AI only if the
   workspace allows it, and is never shared with other workspaces.
5. **Authority level**: whether it is official (*Ufficiale*), informative, or an internal draft.
6. Link it to where it applies (assets, types), and save.

Saving creates the document and its **revision 1, a draft**. On the phone, a document can also start from a
recording or a photo of a page, and **Tidy with AI** writes rough text up (see *Guided and AI-assisted entry*).

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
- **PDF**: opens the page alone in a new tab and the print dialog with it; choose **Save as PDF** as the
  destination. The file is named after the document's code (or the asset's key, or the ticket).
- **Print**: the same page, to paper.

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

- **Knowledge base → Search**, or the search box at the top. On the phone: the **Docs** tab, searched, sorted
  and narrowed to a type.
- **Ask ARGUS** searches documents, tickets, comments and the text of attached files (page by page) by meaning,
  in any language.
- **Related by meaning** on a document lists the equipment, tickets and other documents whose written knowledge
  is about the same thing.
- **Type suggestions** proposes a type for documents that have none.
