# Manifest schema v1

`project.json` is authoritative for project topology; sidecars are authoritative for candidate-generation metadata.

- `steps`: object keyed by `<step_idx>-<sanitized_step_name>`.
- `runs`: append-only queue executions.
- `candidates`: append-only batch outputs with relative image/sidecar/mask paths.
- `versions`: acceptance events containing `version_id` and `accepted_candidate_id`.
- `current_version_id`: active version for a step.
- `input_ref`: source version promoted from a previous step.

Writers use atomic replacement. Schema changes must increment `schema_version` and add migration tests.
