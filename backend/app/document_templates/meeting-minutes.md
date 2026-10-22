---
id: meeting-minutes
version: 1
document_type: Meeting Minutes
title: Meeting minutes
language: en
fields:
  - {key: meeting_date, label: Date of the meeting, type: date, required: true}
  - {key: meeting_time, label: Time, type: text, required: false}
  - {key: place, label: Place or call, type: text, required: false}
  - {key: participants, label: Participants, type: people, required: true}
  - {key: chair, label: Chair, type: person, required: false}
  - {key: minute_taker, label: Minutes by, type: person, required: false}
sections:
  - {key: summary, title: Summary, kind: text, required: true}
  - {key: updates, title: Updates, kind: list, required: false}
  - {key: decisions, title: Decisions, kind: list, required: false}
  - {key: proposals, title: Proposals, kind: list, required: false, description: "suggested but not decided"}
  - {key: actions, title: Actions, kind: table, columns: [action, owner, due], required: false}
  - {key: open_questions, title: Open questions, kind: list, required: false}
  - {key: to_verify, title: To verify, kind: list, required: false, description: "points the source leaves uncertain"}
instructions: |
  Tell decisions (agreed, stated as decided) from proposals (suggested, not agreed) and from updates (reports
  of status). An action has an owner and a due date only if the source names them; otherwise leave those
  cells empty. The meeting date is the date the meeting took place, not the date the text was written or
  sent; a relative date ("tomorrow", "next Monday") is copied as written and reported, the server resolves it.
---
# {{meta:title}}

| | |
|---|---|
| Date | {{field:meeting_date}} |
{{#field:meeting_time}}| Time | {{field:meeting_time}} |
{{/field:meeting_time}}{{#field:place}}| Place | {{field:place}} |
{{/field:place}}| Participants | {{field:participants}} |
{{#field:chair}}| Chair | {{field:chair}} |
{{/field:chair}}{{#field:minute_taker}}| Minutes by | {{field:minute_taker}} |
{{/field:minute_taker}}

## Summary
{{section:summary}}

{{#section:updates}}
## Updates
{{section:updates}}

{{/section:updates}}
{{#section:decisions}}
## Decisions
{{section:decisions}}

{{/section:decisions}}
{{#section:proposals}}
## Proposals
{{section:proposals}}

{{/section:proposals}}
{{#section:actions}}
## Actions
{{section:actions}}

{{/section:actions}}
{{#section:open_questions}}
## Open questions
{{section:open_questions}}

{{/section:open_questions}}
{{#section:to_verify}}
## To verify
{{section:to_verify}}
{{/section:to_verify}}
