---
id: test-report
version: 1
document_type: Test Report
title: Test report
language: en
fields:
  - {key: object, label: Object tested, type: text, required: true}
  - {key: test_date, label: Date of the test, type: date, required: true}
  - {key: performed_by, label: Performed by, type: people, required: false}
  - {key: conclusion, label: Conclusion, type: enum, options: [pass, fail, inconclusive], required: true}
sections:
  - {key: objective, title: Objective, kind: text, required: true}
  - {key: method, title: Method, kind: steps, required: true}
  - {key: instruments, title: Instruments, kind: table, columns: [instrument, identifier, calibration], required: false}
  - {key: criteria, title: Acceptance criteria, kind: list, required: true}
  - {key: data, title: Data, kind: table, columns: [quantity, value, unit, condition], required: true}
  - {key: results, title: Results, kind: text, required: true}
  - {key: deviations, title: Deviations, kind: list, required: false}
instructions: |
  Keep measured data apart from interpretation: data go in the Data table exactly as given, interpretation in
  Results. The conclusion is pass or fail only when both the criteria and the data are in the source and the
  source states, or the data plainly show, the outcome against them; if criteria or data are missing the
  conclusion is absent — never deduce it.
---
# {{meta:title}}

| | |
|---|---|
| Object | {{field:object}} |
| Date | {{field:test_date}} |
{{#field:performed_by}}| Performed by | {{field:performed_by}} |
{{/field:performed_by}}| Conclusion | {{field:conclusion}} |

## Objective
{{section:objective}}

## Method
{{section:method}}

{{#section:instruments}}
## Instruments
{{section:instruments}}

{{/section:instruments}}
## Acceptance criteria
{{section:criteria}}

## Data
{{section:data}}

## Results
{{section:results}}

{{#section:deviations}}
## Deviations
{{section:deviations}}
{{/section:deviations}}
