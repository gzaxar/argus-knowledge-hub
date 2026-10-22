---
id: drawing
version: 1
document_type: Drawing
title: Drawing card
language: en
fields:
  - {key: drawing_number, label: Drawing number, type: text, required: true}
  - {key: drawing_revision, label: Drawing revision, type: text, required: true}
  - {key: discipline, label: Discipline, type: enum, options: [mechanical, electrical, vacuum, cooling, civil, controls, other], required: false}
  - {key: asset, label: Asset, type: text, required: false}
  - {key: original, label: Original, type: reference, required: true, description: "the file, link or archive location of the drawing itself"}
sections:
  - {key: description, title: Description, kind: text, required: true}
  - {key: views, title: Views and sheets, kind: list, required: false}
  - {key: interfaces, title: Interfaces, kind: list, required: false}
  - {key: references_detail, title: References, kind: list, required: false}
instructions: |
  You write a card describing a drawing, not the drawing. Never reconstruct dimensions, tolerances, wiring or
  schematics that are not legible in the source: say what is not legible. The drawing number and revision are
  copied exactly; the original stays the authoritative document.
---
# {{meta:title}}

> {{meta:reference_notice}}

| | |
|---|---|
| Drawing | {{field:drawing_number}} rev. {{field:drawing_revision}} |
{{#field:discipline}}| Discipline | {{field:discipline}} |
{{/field:discipline}}{{#field:asset}}| Asset | {{field:asset}} |
{{/field:asset}}| Original | {{field:original}} |
| Date | {{meta:document_date}} |

## Description
{{section:description}}

{{#section:views}}
## Views and sheets
{{section:views}}

{{/section:views}}
{{#section:interfaces}}
## Interfaces
{{section:interfaces}}

{{/section:interfaces}}
{{#section:references_detail}}
## References
{{section:references_detail}}
{{/section:references_detail}}
