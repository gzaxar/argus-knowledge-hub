---
id: work-instruction
version: 1
document_type: Work Instruction
title: Work instruction
language: en
fields:
  - {key: asset, label: Asset, type: text, required: true, description: "the specific device, with its key or serial"}
  - {key: configuration, label: Configuration, type: text, required: false, description: "model, firmware, variant or setup it is valid for"}
  - {key: duration, label: Expected duration, type: text, required: false}
sections:
  - {key: preparation, title: Preparation, kind: list, required: true}
  - {key: materials, title: Materials, kind: list, required: false}
  - {key: steps, title: Steps, kind: steps, required: true}
  - {key: expected_result, title: Expected result, kind: text, required: true}
  - {key: checks, title: Checks, kind: list, required: false}
  - {key: common_problems, title: Common problems, kind: table, columns: [problem, remedy], required: false}
instructions: |
  A work instruction is for one specific device or context: keep it tied to the asset and configuration the
  source names, and do not generalise it to other models or setups. If the source does not say which device,
  leave the asset absent rather than guessing. No values, torques, settings or part numbers the source does
  not give.
---
# {{meta:title}}

| | |
|---|---|
| Asset | {{field:asset}} |
{{#field:configuration}}| Configuration | {{field:configuration}} |
{{/field:configuration}}{{#field:duration}}| Expected duration | {{field:duration}} |
{{/field:duration}}| Date | {{meta:document_date}} |

## Preparation
{{section:preparation}}

{{#section:materials}}
## Materials
{{section:materials}}

{{/section:materials}}
## Steps
{{section:steps}}

## Expected result
{{section:expected_result}}

{{#section:checks}}
## Checks
{{section:checks}}

{{/section:checks}}
{{#section:common_problems}}
## Common problems
{{section:common_problems}}
{{/section:common_problems}}
