---
id: runbook
version: 1
document_type: Runbook
title: Runbook
language: en
fields:
  - {key: system, label: System, type: text, required: true}
  - {key: alarm, label: Alarm or trigger, type: text, required: false}
  - {key: escalation_contact, label: Escalation contact, type: text, required: false}
sections:
  - {key: symptoms, title: Symptoms, kind: list, required: true}
  - {key: immediate_checks, title: Immediate checks, kind: steps, required: true, description: "observations that change nothing"}
  - {key: safety, title: Safety, kind: list, required: true}
  - {key: diagnosis, title: Diagnosis, kind: steps, required: false}
  - {key: allowed_actions, title: Allowed actions, kind: table, columns: [action, changes the plant, who may do it], required: true}
  - {key: escalation, title: Escalation, kind: list, required: true}
  - {key: recovery, title: Recovery, kind: steps, required: false}
instructions: |
  Keep observations (which change nothing) apart from actions that change the plant (column "changes the
  plant": yes or no). Never invent a bypass, a forced interlock, a reset sequence or an emergency procedure;
  an action is listed only if the source describes it. Who may perform an action only as the source says.
---
# {{meta:title}}

| | |
|---|---|
| System | {{field:system}} |
{{#field:alarm}}| Alarm | {{field:alarm}} |
{{/field:alarm}}{{#field:escalation_contact}}| Escalation | {{field:escalation_contact}} |
{{/field:escalation_contact}}| Date | {{meta:document_date}} |

## Symptoms
{{section:symptoms}}

## Immediate checks
{{section:immediate_checks}}

## Safety
{{section:safety}}

{{#section:diagnosis}}
## Diagnosis
{{section:diagnosis}}

{{/section:diagnosis}}
## Allowed actions
{{section:allowed_actions}}

## Escalation
{{section:escalation}}

{{#section:recovery}}
## Recovery
{{section:recovery}}
{{/section:recovery}}
