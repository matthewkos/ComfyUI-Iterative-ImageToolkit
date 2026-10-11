# ComfyUI Iterative Image Toolkit

A GPL-3.0 ComfyUI node pack for iterative image editing, project-based versioning, prompt and seed restoration, visual comparison, native Mask Editor handoff, and robust edited-crop alignment.

## Nodes

### IIT Save Candidate Run

Treats one queue execution as a `run` and every image in the input batch as a `candidate`. It saves each candidate as PNG plus sidecar JSON and updates `project.json`.

Optional connected inputs:

- `iit_meta` — project/step context from IIT Load Version; overrides the save node project widgets
- `input_mask`
- `positive_prompt`
- `negative_prompt`
- `seed`
- `input_image_name`

### IIT Load Version

Replaces Load Image for iterative projects. Start by uploading/selecting an initial image and entering optional multiline prompts and a seed. Later switch `source` to `current_version` or `candidate` to restore image, mask, prompts, and seed together. It also outputs `IIT_META` with project/step context for IIT Save Candidate Run.

### IIT Locate Edited Crop

Given a larger image A and edited crop B, estimates translation, uniform scale, and rotation from background features. It refines diagnostics with dense optical flow, allowing localized inpainting or object movement to behave as outliers.

Outputs:

- Axis-aligned `BBOX`
- Rotated `ROTATED_BBOX` quadrilateral
- A crop from A aligned to B
- Confidence score
- Diagnostic heatmap as `IMAGE`
- Full diagnostics JSON

## Storage

Blank `storage_root` uses:

```text
ComfyUI/output/iterative-image-toolkit/<project>/
```

An explicit absolute path is supported. Project layout:

```text
<project>/
├── project.json
├── 01-color/runs/run-0001/
│   ├── image-run-0001-candidate-001.png
│   ├── image-run-0001-candidate-001.json
│   └── image-input-mask.png
└── 02-reshape/
```

Accepted versions are manifest records that reference `accepted_candidate_id`; candidate images are not copied.

## Install

Clone into ComfyUI's `custom_nodes` directory and install dependencies:

```bash
git clone https://github.com/OWNER/ComfyUI-Iterative-ImageToolkit.git
cd ComfyUI-Iterative-ImageToolkit
python -m pip install -r requirements.txt
```

Restart ComfyUI and find the nodes under **Iterative Image Toolkit**.

## Mask Editor workflow

IIT Load Version uses the same `image` upload/selection contract as Load Image, so initial images can use ComfyUI native Mask Editor directly. For a saved candidate, select it in the Version Browser and click **Stage for Mask Editor**; the staged input is selected on the same IIT Load Version node.

## Development

```bash
python -m pip install -r requirements-dev.txt
ruff check .
pytest
```

Read [`AGENTS.md`](AGENTS.md) before contributing.

## Registry publishing

Before publishing, replace `OWNER` URLs and `REPLACE_WITH_PUBLISHER_ID` in `pyproject.toml`. The intended Registry package ID is `iterative-image-toolkit` and display name is **Iterative Image Toolkit**.

## Limitations

- The MVP uses local SIFT/ORB features, RANSAC similarity transforms, and Farneback flow. It is not intended for perspective deformation.
- Textureless backgrounds may not contain enough features for a reliable match.
- Confidence is a heuristic quality score, not a calibrated probability.
- The browser currently stages a selected image for the native Mask Editor rather than opening the editor directly because native editor integration is owned by the Load Image UI contract.
