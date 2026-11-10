---
title: Document hierarchy and subsystem pages
summary: Browsing documents by hierarchy or type; WP subsystem roots, folders, moving pages, previews, icons, counts and unfiled documents.
keywords: [hierarchy, gerarchia, subsystem, subsystems, sottosistemi, WP01, WP02, work package, folder, cartella, move, sposta, parent, child, imported parent, unfiled, shared, document types, icon, counter, count, breadcrumb, preview, full table, page, list]
order: 82
---

**Documents** has two ways to browse the same readable documents: **Hierarchy** follows folders and parent
pages; **Document types** groups records by their assigned type. Changing the view does not copy or reclassify
documents. For writing, review, publication and templates, see *Documents and the knowledge base*.

## Browse the hierarchy

1. Choose the correct workspace, then open **Documents → Hierarchy**.
2. Expand a branch with its arrow, or use **Expand all**. **Collapse all** closes the branches.
3. Select a document to read its **Page** preview. Select **List** to browse documents in the selected branch.
4. Use the breadcrumbs above the preview to return to a parent page or folder.
5. **Find a document or folder…** searches titles and document codes in the browser; matching pages keep their
   ancestors visible so their location is clear. It is separate from the site's global search and from Ask
   ARGUS's search inside written content.

The full document body is not searched by this local navigation box. For content, use global search, the
document table's search tools or Ask ARGUS, as appropriate.

## WP subsystem pages at the top level

In a workspace using the WP naming convention, overview pages such as **WP01 - Magnets & Power Supplies**
and **WP02 - RF sources & RF distribution** are themselves the navigation entry for each subsystem. A second
folder called *Subsystems* is unnecessary.

Root page titles starting with a WP number are recognised, including `WP01`, `WP-01`, `WP_01` and `WP 01`.
They appear at the top level even if they have no children. A WP page already placed under a folder or another
page stays there. Ambiguous source parents and cycles are not automatically turned into subsystem roots.

For example, a WP02 overview can contain:

- **How-to connect the modulator to the network**;
- **How-to turn modulators on and off**.

The WP page remains a document with its own type and revisions. Its position does not turn it into a folder,
change its type, or link it to equipment. The WP naming convention is a navigation convention, not a universal
claim that every project's work package is a technical subsystem.

## What Unfiled documents means

**Unfiled documents** is a navigation group for ordinary pages with no usable parent or folder placement.
It does not mean their files are missing, their import failed, or they have no document type. A parent page
inside this group can still have correctly linked child pages.

Choose the correct destination before moving a page. A standalone modulator test procedure, for example,
belongs under WP02 only if its owner confirms that subsystem is its scope. Titles alone do not assign an
unfiled procedure to a WP. The group disappears when no pages need it.

If an imported parent was outside the selected import subtree, ARGUS does not fabricate it. Import the intended
scope or organise the page manually. Warnings about multiple parents or cycles need review; do not hide a
structural problem by creating duplicate documents.

## Create and maintain folders

1. Select a folder if the new one should go inside it, then choose **+ Folder**.
2. Enter **Folder name**. Choose **Parent folder**, or **Top level**, then **Save**.
3. To rename or move a folder, select it and choose **Edit folder**.
4. To remove an unused folder, choose **Edit folder → Delete empty folder** and confirm. It must contain no
   subfolders or placed documents. Move its contents first if deletion is refused.

A folder is a navigation container: it has no controlled-document code, body, approval state or revisions.
For an overview with technical content, use a document page. Folder names do not set document confidentiality
or grant access to their contents.

If an earlier layout contains **(0) Subsystems**, select it and use **Edit folder → Delete empty folder**.
This removes the empty container; it does not delete WP01, WP02 or their documents elsewhere in the tree.

## Move a document under a folder or another page

1. Select the document, open **Page**, and find **Move in hierarchy** below its content. Scroll down if needed.
2. Under **Place under**, choose the destination folder or the entry **Document: …** for the parent page.
3. Choose **Save**. Expand the destination to check the result; refresh to confirm the placement persists.

Its child pages follow it. For example, moving a WP02 overview moves its two how-to pages with it. A move
changes navigation placement, not document content, revision state, owning workspace or equipment relations.
You cannot move a page inside itself or one of its descendants. Use this control; drag-and-drop is not
implemented in this version.

**Use relationship / imported parent** removes the manual placement and follows the available source parent
again. A manual placement is otherwise kept when the Confluence import runs again.

The current destination list calls the no-parent choice **Unfiled documents**. For an ordinary page this puts
it in that group; for a WP-prefixed overview it explicitly places the page at the top level. Thus, if a WP page
remains unfiled because its source parent is unavailable, this choice can make it an explicit subsystem root.

## Add a child document

Select the parent page and choose **+ Add child document**, then complete and save the normal document form.
The new draft is placed under that page. With a folder selected, **+ New document here** starts a document
inside it. Neither action publishes the draft. Select the parent carefully; avoid making a second copy of an
existing page just to change where it appears.

## Document types and icons

**Document types** groups the same documents by their assigned type, such as Procedure, Design Report or Work
Instruction. The icon beside a type, a document and its preview follows the type's configured icon. A type
without a configured icon uses a generic document symbol. Real folders and the Unfiled/Shared groups use
folder symbols.

Moving a document does not change its type or icon. A WP overview can have type *Document* while a child has
type *Work Instruction*. If the type is wrong, use the document's editing or **Full table** controls; changing
the title or creating a folder is not a type correction.

## Read the counters

Counts include documents you may read, including readable shared documents; revisions are not separate
documents. They describe the whole readable branch, not just the rows currently expanded or matched by a
local search.

| Counter | Meaning |
|---|---|
| **Documents (n)** and **(n) Total documents** | Unique readable document records in the browser |
| **(n) Procedure**, or another type group | Documents assigned to that group |
| A folder or **Unfiled documents** | Unique documents anywhere below it, including overview pages |
| **(2) WP02 …** | Two descendant documents; the WP02 overview itself is excluded from this branch counter |

A leaf document does not show a redundant `(0)`. If WP02 and its two how-to pages are the only records, the
total is **3**, while WP02's branch counter is **2**. A folder containing them would show **3**.

## Preview and revision selection

The browser can show an open **Draft**, **In review** or **Approved** revision before the published one.
Check the state badge and **Revision** selector: the preview is not a guarantee that the displayed text is the
released instruction. Choose the published revision before using a controlled procedure.

The preview shows available content, summary, document type, source-space metadata and files linked in the
body. **Open full document** opens the selected revision in the full document page for its normal editing,
review and file controls. A repeated first heading may be omitted in the preview to avoid showing the title
twice; the stored body is unchanged.

An imported Confluence page can display **From Confluence** and **Published**. These describe its source and
imported revision state; they do not by themselves demonstrate approval under your local controlled-document
process. Check source, authority, scope and revision before use.

## Shared documents and permissions

**Shared documents** contains readable documents owned by another workspace. In this browser, the receiving
workspace can preview only the owner's current published revision, not its drafts. Organise or edit a shared
document in its owning workspace with the appropriate permissions.

Creating folders and child documents needs document-create rights; moving or renaming needs document-modify
rights; deleting an empty folder needs document-delete rights. Missing buttons can reflect your role or a
foreign document's ownership. Ask the workspace administrator if the expected controls are absent.

## Return to the full table

Use **Full table** for the existing advanced document filters, columns, sorting and bulk operations, including
copying, moving between workspaces, deletion and retyping. Those operations differ from **Move in hierarchy**,
which only organises a page inside its owning workspace. The table and browser show the same records; neither
creates another library.
