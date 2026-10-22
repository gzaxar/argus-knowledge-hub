---
id: safety-document
version: 1
document_type: Safety Document
title: Safety document
language: en
fields:
  - {key: area, label: Area or equipment, type: text, required: true}
  - {key: safety_officer, label: Safety contact, type: person, required: false}
  - {key: references, label: Regulations and references, type: list, required: false}
sections:
  - {key: scope, title: Scope, kind: text, required: true}
  - {key: hazards, title: Hazards, kind: table, columns: [hazard, source, consequence], required: true}
  - {key: exposed, title: People exposed, kind: list, required: true}
  - {key: measures, title: Protective measures, kind: list, required: true}
  - {key: access, title: Access, kind: list, required: false, description: "who may enter or operate and on what conditions"}
  - {key: controls, title: Checks and inspections, kind: list, required: false}
  - {key: response, title: Response to anomalies, kind: steps, required: true}
  - {key: references_detail, title: References, kind: list, required: false}
instructions: |
  Write only the hazards, risk levels, limits, obligations, authorisations and approvals the source states.
  Never assign a risk level, a dose or exposure limit, a PPE requirement or an approval the source does not
  give: leave it absent and list it as missing. An emergency response is reproduced as the source states it,
  never completed.
---
# {{meta:title}}

| | |
|---|---|
| Area | {{field:area}} |
{{#field:safety_officer}}| Safety contact | {{field:safety_officer}} |
{{/field:safety_officer}}| Date | {{meta:document_date}} |

## Scope
{{section:scope}}

## Hazards
{{section:hazards}}

## People exposed
{{section:exposed}}

## Protective measures
{{section:measures}}

{{#section:access}}
## Access
{{section:access}}

{{/section:access}}
{{#section:controls}}
## Checks and inspections
{{section:controls}}

{{/section:controls}}
## Response to anomalies
{{section:response}}

{{#section:references_detail}}
## References
{{section:references_detail}}
{{/section:references_detail}}
{{#field:references}}
Regulations: {{field:references}}
{{/field:references}}
