---
id: maintenance-report
version: 1
document_type: Maintenance Report
title: Maintenance report
language: en
fields:
  - {key: asset, label: Asset, type: text, required: true}
  - {key: intervention_date, label: Date of the intervention, type: date, required: true}
  - {key: technicians, label: Technicians, type: people, required: false}
  - {key: ticket, label: Ticket, type: text, required: false}
  - {key: final_state, label: Final state, type: enum, options: [in service, in service with limitations, out of service], required: true}
sections:
  - {key: reason, title: Reason, kind: text, required: true}
  - {key: initial_state, title: Initial state, kind: text, required: false}
  - {key: diagnosis, title: Diagnosis, kind: table, columns: [finding, kind], required: false, description: "kind is symptom, suspected cause or confirmed cause"}
  - {key: interventions, title: Work done, kind: steps, required: true}
  - {key: spare_parts, title: Spare parts, kind: table, columns: [part, quantity, identifier], required: false}
  - {key: final_tests, title: Final tests, kind: list, required: false}
  - {key: open_actions, title: Open actions, kind: list, required: false}
instructions: |
  Tell a symptom from a suspected cause and from a confirmed cause (the "kind" column), as the source does: a
  cause is "confirmed" only if the source says it was found or verified. Parts and quantities exactly as given.
  The final state only as the source reports it.
---
# {{meta:title}}

| | |
|---|---|
| Asset | {{field:asset}} |
| Date | {{field:intervention_date}} |
{{#field:technicians}}| Technicians | {{field:technicians}} |
{{/field:technicians}}{{#field:ticket}}| Ticket | {{field:ticket}} |
{{/field:ticket}}| Final state | {{field:final_state}} |

## Reason
{{section:reason}}

{{#section:initial_state}}
## Initial state
{{section:initial_state}}

{{/section:initial_state}}
{{#section:diagnosis}}
## Diagnosis
{{section:diagnosis}}

{{/section:diagnosis}}
## Work done
{{section:interventions}}

{{#section:spare_parts}}
## Spare parts
{{section:spare_parts}}

{{/section:spare_parts}}
{{#section:final_tests}}
## Final tests
{{section:final_tests}}

{{/section:final_tests}}
{{#section:open_actions}}
## Open actions
{{section:open_actions}}
{{/section:open_actions}}
