---
id: note
version: 1
document_type: Note
title: Note
language: en
fields:
  - {key: topic, label: Topic, type: text, required: false}
  - {key: author, label: Author, type: person, required: false}
sections:
  - {key: context, title: Context, kind: text, required: false}
  - {key: content, title: Content, kind: text, required: true, description: "the content organised by theme, under bold theme names"}
  - {key: observations, title: Observations, kind: list, required: false}
  - {key: conclusions, title: Conclusions, kind: list, required: false, description: "only if the source draws them"}
  - {key: links, title: Links, kind: list, required: false}
  - {key: follow_up, title: To look into, kind: list, required: false}
instructions: |
  Keep hypotheses and opinions as such ("X thinks that…", "possibly…"); do not turn them into facts.
  Organise by theme without dropping content. Suggest another document type only when the source is clearly
  one (a procedure, minutes of a meeting, a test report): say so in suggested_type.
---
# {{meta:title}}

{{#field:topic}}**Topic:** {{field:topic}}
{{/field:topic}}{{#field:author}}**Author:** {{field:author}}
{{/field:author}}**Date:** {{meta:document_date}}

{{#section:context}}
## Context
{{section:context}}

{{/section:context}}
## Content
{{section:content}}

{{#section:observations}}
## Observations
{{section:observations}}

{{/section:observations}}
{{#section:conclusions}}
## Conclusions
{{section:conclusions}}

{{/section:conclusions}}
{{#section:links}}
## Links
{{section:links}}

{{/section:links}}
{{#section:follow_up}}
## To look into
{{section:follow_up}}
{{/section:follow_up}}
