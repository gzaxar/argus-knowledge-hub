---
id: procedure
version: 1
document_type: Procedure
title: Procedure
language: en
fields:
  - {key: system, label: System or equipment, type: text, required: true}
  - {key: applicability, label: Applies to, type: text, required: false, description: "configurations, areas or states it covers"}
  - {key: owner, label: Responsible, type: person, required: false}
sections:
  - {key: purpose, title: Purpose, kind: text, required: true}
  - {key: scope, title: Scope, kind: text, required: true}
  - {key: prerequisites, title: Prerequisites, kind: list, required: true}
  - {key: safety, title: Safety, kind: list, required: true, description: "hazards, protective measures and authorisations the source names"}
  - {key: tools, title: Tools and materials, kind: list, required: false}
  - {key: steps, title: Steps, kind: steps, required: true}
  - {key: checks, title: Checks, kind: list, required: true, description: "how to tell the procedure worked"}
  - {key: anomalies, title: Anomalies, kind: table, columns: [symptom, action], required: false}
  - {key: recovery, title: Recovery, kind: steps, required: false, description: "how to return to a safe state"}
  - {key: references_detail, title: References, kind: list, required: false}
instructions: |
  A procedure is a sequence somebody follows. Turn the source into steps only where it actually describes
  what to do; a report of what was done once ("we opened V3, then…") is not by itself an instruction:
  mark such steps "inferred" and say so in an ambiguity. Never write a command, a setpoint, an interlock or a
  safety condition the source does not give: leave it absent. Keep the order of steps as the source gives it.
---
# {{meta:title}}

| | |
|---|---|
| System | {{field:system}} |
{{#field:applicability}}| Applies to | {{field:applicability}} |
{{/field:applicability}}{{#field:owner}}| Responsible | {{field:owner}} |
{{/field:owner}}| Date | {{meta:document_date}} |

## Purpose
{{section:purpose}}

## Scope
{{section:scope}}

## Prerequisites
{{section:prerequisites}}

## Safety
{{section:safety}}

{{#section:tools}}
## Tools and materials
{{section:tools}}

{{/section:tools}}
## Steps
{{section:steps}}

## Checks
{{section:checks}}

{{#section:anomalies}}
## Anomalies
{{section:anomalies}}

{{/section:anomalies}}
{{#section:recovery}}
## Recovery
{{section:recovery}}

{{/section:recovery}}
{{#section:references_detail}}
## References
{{section:references_detail}}
{{/section:references_detail}}
