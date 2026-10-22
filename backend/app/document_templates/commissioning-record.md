---
id: commissioning-record
version: 1
document_type: Commissioning Record
title: Commissioning record
language: en
fields:
  - {key: system, label: System or asset, type: text, required: true}
  - {key: configuration, label: Configuration, type: text, required: true}
  - {key: commissioning_date, label: Date of commissioning, type: date, required: true}
  - {key: participants, label: Performed by, type: people, required: false}
  - {key: final_status, label: Final status, type: enum, options: [accepted, accepted with limitations, not accepted, not concluded], required: true}
sections:
  - {key: prerequisites, title: Prerequisites, kind: list, required: false}
  - {key: tests, title: Tests, kind: table, columns: [test, planned or performed, outcome], required: true}
  - {key: measurements, title: Measurements, kind: table, columns: [quantity, value, unit, condition], required: false}
  - {key: deviations, title: Deviations, kind: list, required: false}
  - {key: limitations, title: Limitations, kind: list, required: false}
  - {key: attachments, title: Attachments, kind: list, required: false}
instructions: |
  Tell tests that were planned from tests that were performed (the "planned or performed" column), and give an
  outcome only where the source documents it. The final status is "accepted" only if the source records the
  acceptance; otherwise leave it absent. Measurements with value and unit exactly as given.
---
# {{meta:title}}

| | |
|---|---|
| System | {{field:system}} |
| Configuration | {{field:configuration}} |
| Date | {{field:commissioning_date}} |
{{#field:participants}}| Performed by | {{field:participants}} |
{{/field:participants}}| Final status | {{field:final_status}} |

{{#section:prerequisites}}
## Prerequisites
{{section:prerequisites}}

{{/section:prerequisites}}
## Tests
{{section:tests}}

{{#section:measurements}}
## Measurements
{{section:measurements}}

{{/section:measurements}}
{{#section:deviations}}
## Deviations
{{section:deviations}}

{{/section:deviations}}
{{#section:limitations}}
## Limitations
{{section:limitations}}

{{/section:limitations}}
{{#section:attachments}}
## Attachments
{{section:attachments}}
{{/section:attachments}}
