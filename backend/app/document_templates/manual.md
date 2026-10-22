---
id: manual
version: 1
document_type: Manual
title: Manual card
language: en
fields:
  - {key: manufacturer, label: Manufacturer, type: text, required: true}
  - {key: model, label: Model, type: text, required: true}
  - {key: manual_version, label: Manual version, type: text, required: false}
  - {key: applicability, label: Applies to, type: text, required: false, description: "models, serials or firmware the manual covers"}
  - {key: original, label: Original, type: reference, required: true, description: "the file, link or archive location of the manual"}
sections:
  - {key: contents, title: Contents, kind: table, columns: [chapter, what it covers], required: true, description: "a reasoned index of the manual"}
  - {key: use, title: Use, kind: list, required: false}
  - {key: maintenance, title: Maintenance, kind: list, required: false}
  - {key: diagnostics, title: Diagnostics, kind: list, required: false}
  - {key: original_references, title: Where to look in the original, kind: table, columns: [topic, chapter or page], required: false}
instructions: |
  You write a card and a reasoned summary of a manual, never a replacement for it. Point to chapters and pages
  of the original for anything that matters; never copy long passages and never paraphrase a safety warning
  into something weaker. Values, settings and part numbers are given only with their chapter or page.
---
# {{meta:title}}

> {{meta:reference_notice}}

| | |
|---|---|
| Manufacturer | {{field:manufacturer}} |
| Model | {{field:model}} |
{{#field:manual_version}}| Manual version | {{field:manual_version}} |
{{/field:manual_version}}{{#field:applicability}}| Applies to | {{field:applicability}} |
{{/field:applicability}}| Original | {{field:original}} |

## Contents
{{section:contents}}

{{#section:use}}
## Use
{{section:use}}

{{/section:use}}
{{#section:maintenance}}
## Maintenance
{{section:maintenance}}

{{/section:maintenance}}
{{#section:diagnostics}}
## Diagnostics
{{section:diagnostics}}

{{/section:diagnostics}}
{{#section:original_references}}
## Where to look in the original
{{section:original_references}}
{{/section:original_references}}
