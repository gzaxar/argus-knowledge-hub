---
id: design-report
version: 1
document_type: Design Report
title: Design report
language: en
fields:
  - {key: subject, label: Subject, type: text, required: true}
  - {key: authors, label: Authors, type: people, required: false}
  - {key: decision_status, label: Decision status, type: enum, options: [proposed, under discussion, approved], required: false}
sections:
  - {key: problem, title: Problem, kind: text, required: true}
  - {key: requirements, title: Requirements, kind: list, required: true}
  - {key: solution, title: Proposed solution, kind: text, required: true}
  - {key: alternatives, title: Alternatives considered, kind: table, columns: [alternative, why not chosen], required: false}
  - {key: calculations, title: Calculations, kind: list, required: false}
  - {key: assumptions, title: Assumptions, kind: list, required: false}
  - {key: rationale, title: Rationale, kind: text, required: false}
  - {key: limits, title: Limits, kind: list, required: false}
  - {key: verification, title: Verification, kind: list, required: false}
instructions: |
  Keep three things apart: data taken from the source (present), your interpretation of it (inferred), and
  decisions the source says were approved. A decision is "approved" only when the source says who approved it
  or that it was approved; otherwise the decision status is proposed or under discussion, or absent.
  Reproduce calculations and numbers as given, with their units; never complete or recompute them.
---
# {{meta:title}}

| | |
|---|---|
| Subject | {{field:subject}} |
{{#field:authors}}| Authors | {{field:authors}} |
{{/field:authors}}{{#field:decision_status}}| Decision status | {{field:decision_status}} |
{{/field:decision_status}}| Date | {{meta:document_date}} |

## Problem
{{section:problem}}

## Requirements
{{section:requirements}}

## Proposed solution
{{section:solution}}

{{#section:alternatives}}
## Alternatives considered
{{section:alternatives}}

{{/section:alternatives}}
{{#section:calculations}}
## Calculations
{{section:calculations}}

{{/section:calculations}}
{{#section:assumptions}}
## Assumptions
{{section:assumptions}}

{{/section:assumptions}}
{{#section:rationale}}
## Rationale
{{section:rationale}}

{{/section:rationale}}
{{#section:limits}}
## Limits
{{section:limits}}

{{/section:limits}}
{{#section:verification}}
## Verification
{{section:verification}}
{{/section:verification}}
