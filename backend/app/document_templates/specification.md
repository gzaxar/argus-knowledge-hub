---
id: specification
version: 1
document_type: Specification
title: Specification
language: en
fields:
  - {key: subject, label: Subject, type: text, required: true, description: "the system, component or service specified"}
  - {key: requester, label: Requested by, type: person, required: false}
  - {key: status, label: Status, type: enum, options: [proposal, agreed, frozen], required: false}
sections:
  - {key: purpose, title: Purpose, kind: text, required: true}
  - {key: functional, title: Functional requirements, kind: table, columns: [id, requirement, binding], required: true, description: "binding is \"must\" for a requirement, \"should\" for a preference, \"assumption\" for an assumption"}
  - {key: performance, title: Performance requirements, kind: table, columns: [id, quantity, value, unit], required: false}
  - {key: interfaces, title: Interfaces, kind: list, required: false}
  - {key: constraints, title: Constraints, kind: list, required: false}
  - {key: acceptance, title: Acceptance criteria, kind: list, required: true}
  - {key: open_questions, title: Open questions, kind: list, required: false}
instructions: |
  Keep binding requirements, preferences and assumptions apart (the "binding" column: must, should or
  assumption), as the source words them. Number requirements only if the source does not; keep its numbers
  if it does. Never create an acceptance criterion, a tolerance or a value the source does not state: list
  what is missing under open questions.
---
# {{meta:title}}

| | |
|---|---|
| Subject | {{field:subject}} |
{{#field:requester}}| Requested by | {{field:requester}} |
{{/field:requester}}{{#field:status}}| Status | {{field:status}} |
{{/field:status}}| Date | {{meta:document_date}} |

## Purpose
{{section:purpose}}

## Functional requirements
{{section:functional}}

{{#section:performance}}
## Performance requirements
{{section:performance}}

{{/section:performance}}
{{#section:interfaces}}
## Interfaces
{{section:interfaces}}

{{/section:interfaces}}
{{#section:constraints}}
## Constraints
{{section:constraints}}

{{/section:constraints}}
## Acceptance criteria
{{section:acceptance}}

{{#section:open_questions}}
## Open questions
{{section:open_questions}}
{{/section:open_questions}}
