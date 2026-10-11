# Manifest schema v1

`project.json` is authoritative for project topology; sidecars are authoritative for candidate-generation metadata.

- `steps`: object keyed by `<step_idx>-<sanitized_step_name>`.
- `runs`: append-only queue executions.
- `candidates`: append-only batch outputs with relative image/sidecar/mask paths.
- `versions`: acceptance events containing `version_id` and `accepted_candidate_id`.
- `current_version_id`: active version for a step.
- `input_ref`: source version promoted from a previous step.

Writers use atomic replacement. Schema changes must increment `schema_version` and add migration tests.

## Initial input and promotion lineage

New projects may record the first loader input once at project level:

```json
{
  "initial_input": {
    "image": "portrait.png",
    "positive_prompt": "warm portrait",
    "negative_prompt": "artifacts",
    "seed": 42
  }
}
```

A current accepted version may record where it was promoted:

```json
{
  "version_id": "ver-02",
  "accepted_candidate_id": "run-0003-candidate-002",
  "promoted_to_step_key": "02-reshape"
}
```

The destination step resolves `source=promoted_input` through its `input_ref`:

```json
{
  "input_ref": {
    "step_key": "01-color",
    "version_id": "ver-02",
    "candidate_id": "run-0003-candidate-002",
    "promoted_at": "2026-10-12T00:00:00+00:00"
  }
}
```

These fields are optional for backward compatibility. A missing `initial_input` appears as an unavailable initial card in IIT View Trajectory rather than preventing the project from loading.
