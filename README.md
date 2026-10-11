# ComfyUI Iterative Image Toolkit

A GPL-3.0 ComfyUI node pack for iterative image editing, project-based versioning, prompt and seed restoration, visual comparison, native Mask Editor handoff, and robust edited-crop alignment.

## Nodes

### IIT Save Candidate Run

Treats one queue execution as a `run` and every image in the input batch as a `candidate`. It saves each candidate as PNG plus sidecar JSON and updates `project.json`.

Optional connected inputs:

- `input_mask`
- `positive_prompt`
- `negative_prompt`
- `seed`
- `input_image_name`

### IIT Load Version

Loads either the current accepted version or a candidate. It returns `IMAGE`, `MASK`, positive prompt, negative prompt, seed, and metadata JSON. Use **Open Version Browser** to compare candidates, set the current version, promote it to the next step, or stage it under ComfyUI input for the native Mask Editor.

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

1. Open **IIT Load Version → Open Version Browser**.
2. Select a candidate and click **Stage for Mask Editor**.
3. Add a native **Load Image** node and select the staged file shown in the notification.
4. Right-click that node and choose **Open in Mask Editor**.
5. Connect its `IMAGE` and `MASK` outputs to the editing workflow.

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
