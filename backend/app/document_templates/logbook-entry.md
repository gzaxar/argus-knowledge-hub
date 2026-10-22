---
id: logbook-entry
version: 1
document_type: Logbook Entry
title: Logbook entry
language: en
fields:
  - {key: shift, label: Shift, type: text, required: true, description: "date and shift as the source gives them"}
  - {key: operators, label: Operators, type: people, required: false}
  - {key: machine_configuration, label: Machine configuration, type: text, required: false}
sections:
  - {key: timeline, title: Timeline, kind: table, columns: [time, event], required: true}
  - {key: observations, title: Observations, kind: list, required: false}
  - {key: interventions, title: Interventions, kind: list, required: false}
  - {key: anomalies, title: Anomalies, kind: list, required: false}
  - {key: handover, title: Handover, kind: list, required: true, description: "what the next shift must know or do"}
instructions: |
  Keep the order of events as they happened. A time is written only if the source gives it; an event without
  a time keeps its place in the order with an empty time. Never invent times or authors.
---
# {{meta:title}}

| | |
|---|---|
| Shift | {{field:shift}} |
{{#field:operators}}| Operators | {{field:operators}} |
{{/field:operators}}{{#field:machine_configuration}}| Configuration | {{field:machine_configuration}} |
{{/field:machine_configuration}}

## Timeline
{{section:timeline}}

{{#section:observations}}
## Observations
{{section:observations}}

{{/section:observations}}
{{#section:interventions}}
## Interventions
{{section:interventions}}

{{/section:interventions}}
{{#section:anomalies}}
## Anomalies
{{section:anomalies}}

{{/section:anomalies}}
## Handover
{{section:handover}}
