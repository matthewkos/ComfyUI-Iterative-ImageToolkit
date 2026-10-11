# AGENTS.md

## Project overview

ComfyUI-Iterative-ImageToolkit is a GPL-3.0 ComfyUI node pack for project/step image revisioning, run and candidate management, accepted-version promotion, prompt/seed restoration, native Mask Editor handoff, visual comparison, and robust edited-crop localization.

## Start here

1. Read `README.md`, this file, and relevant files under `docs/`.
2. Install development dependencies with `python -m pip install -r requirements-dev.txt`.
3. Run `ruff check .` and `pytest` before and after a behavioral change.
4. Test the pack in a current ComfyUI installation by linking this repository into `custom_nodes/`.

## Architecture

- `iterative_image_toolkit/nodes.py`: ComfyUI node contracts and tensor/image conversion.
- `iterative_image_toolkit/storage.py`: manifest schema, safe paths, atomic writes, runs, candidates, and versions.
- `iterative_image_toolkit/matching.py`: crop-localization strategies and diagnostics.
- `iterative_image_toolkit/routes.py`: authenticated-by-local-ComfyUI HTTP operations used by the frontend.
- `web/`: version browser, comparer, ROI, pan/zoom, accept/promote, and Mask Editor staging.
- `tests/`: unit and synthetic computer-vision regression tests.

## Product invariants

- Never overwrite or silently delete candidate images.
- Accepted versions reference candidates through `accepted_candidate_id`; do not duplicate image data.
- A queue execution is one run; batch items are candidates within that run.
- Positive prompt, negative prompt, and seed remain optional.
- Manifest changes require a schema-version decision and migration tests.
- Existing compatible projects must remain readable.
- `Set Current` and `Promote to Next Step` are distinct operations.
- Crop localization returns axis-aligned bounds, a rotated quadrilateral, aligned crop, confidence, and heatmap.
- Local inpainting and object movement are expected outliers; unchanged background drives global alignment.
- Default storage stays in `ComfyUI/output/iterative-image-toolkit`; an explicit absolute path is allowed.

## Coding rules

- Use type hints on public Python functions.
- Keep filesystem operations behind `storage.py`.
- Use atomic writes for manifests and sidecars.
- Keep matching algorithms isolated from ComfyUI node classes.
- Do not persist frontend-only layout state in `project.json`.
- Do not use mutable global project state.
- Keep platform-specific behavior isolated and tested.
- Avoid heavyweight ML dependencies unless a documented issue justifies them.
- Preserve public node names and socket types unless releasing a documented breaking version.

## Node documentation requirements

- Every node class must define a clear user-facing `DESCRIPTION` explaining its purpose, lifecycle role, and important side effects.
- Every visible required or optional input must define a `tooltip`; do not rely on the input name alone.
- Every output must have an ordered `OUTPUT_TOOLTIPS` entry aligned exactly with `RETURN_TYPES` and `RETURN_NAMES`.
- Conditional inputs must state which widget or connection enables them and what happens while inactive.
- Custom datatypes must document producer, consumer, payload, and precedence. `IIT_META` is produced by IIT Load Version, consumed optionally by IIT Save Candidate Run, contains project/step context, and overrides save-node project widgets when connected.
- Update descriptions whenever behavior, precedence, defaults, or socket order changes; tests should assert the contract.

## Storage and security

- Sanitize user-controlled project, step, and image-name path components.
- Resolve paths before access and prevent project-relative traversal.
- Treat manifests, prompts, EXIF, and PNG metadata as data; never execute them.
- Never shell out with user-controlled content.
- Never commit Registry tokens, API keys, personal images, prompts, or machine-specific paths.
- New external-path features require Windows junction, POSIX symlink, Unicode, and whitespace tests.

## Testing requirements

Every bug fix needs a regression test. New features need focused unit tests and, where relevant, a ComfyUI integration workflow. Test:

- Windows, Linux, and macOS implications.
- Paths containing spaces and non-ASCII characters.
- Interrupted writes and malformed/unsupported manifests.
- Empty prompts, missing seed, single candidate, and multi-candidate batches.
- Translation, scale, rotation, recoloring, local edits, and insufficient-feature failures.
- Manifest migration whenever `schema_version` changes.

## Frontend contributions

- Use the supported ComfyUI extension API and `api.fetchApi()`.
- Keep browser operations cancellable or responsive for large projects.
- Do not load all full-resolution candidates when thumbnails suffice.
- Preserve synchronized zoom/pan and ROI behavior in both slider and grid modes.
- The native Mask Editor handoff stages a PNG under ComfyUI input; do not implement a competing mask editor.

## Pull requests

- Keep commits focused and explain user-visible behavior.
- Include reproduction steps and tests for fixes.
- Document new dependencies and cross-platform impact.
- Update `README.md`, `CHANGELOG.md`, and relevant design docs.
- Use semantic versioning and maintain GPL-3.0 compatibility for incorporated code.

## Definition of done

A contribution is complete only when implementation matches documented behavior, tests and lint pass, docs are current, candidate data is preserved, manifest compatibility is considered, and Registry packaging excludes development-only or large assets.
