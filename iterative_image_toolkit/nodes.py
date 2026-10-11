from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import folder_paths
import numpy as np
import torch
from PIL import Image

from .matching import diagnostics_json, locate_crop
from .storage import (
    atomic_write_json,
    candidate_path,
    find_candidate,
    find_step,
    load_manifest,
    project_dir,
    register_run,
    resolve_selection,
    resolve_storage_root,
    slug,
    utc_now,
)

CATEGORY = "Iterative Image Toolkit"


def tensor_to_rgb(image: torch.Tensor) -> np.ndarray:
    return np.clip(image.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)


def numpy_to_tensor(image: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(image.astype(np.float32) / 255.0).unsqueeze(0)


def load_image_and_mask(path: Path) -> tuple[torch.Tensor, torch.Tensor]:
    source = Image.open(path)
    rgb = np.asarray(source.convert("RGB"), dtype=np.float32) / 255.0
    image = torch.from_numpy(rgb).unsqueeze(0)
    if "A" in source.getbands():
        alpha = np.asarray(source.getchannel("A"), dtype=np.float32) / 255.0
        mask = 1.0 - torch.from_numpy(alpha).unsqueeze(0)
    else:
        mask = torch.zeros((1, source.height, source.width), dtype=torch.float32)
    return image, mask


def save_mask(mask: torch.Tensor, path: Path) -> None:
    array = np.clip(mask.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
    if array.ndim == 3:
        array = array[0]
    Image.fromarray(array, mode="L").save(path, format="PNG")


class IITSaveCandidates:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "The image batch to save as candidates. One execution creates one run, "
                            "and each image in the batch becomes a separate candidate in that run."
                        )
                    },
                ),
                "project_name": (
                    "STRING",
                    {
                        "default": "my-project",
                        "tooltip": (
                            "Name of the editing project. It identifies the project's storage folder "
                            "and groups all steps, runs, candidates, and accepted versions."
                        ),
                    },
                ),
                "step_idx": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 9999,
                        "tooltip": (
                            "Numeric order of this editing step, such as 1 for color correction or "
                            "2 for reshaping. It is used in the step folder name."
                        ),
                    },
                ),
                "step_name": (
                    "STRING",
                    {
                        "default": "edit",
                        "tooltip": (
                            "Human-readable name of this editing step, such as 'color', 'reshape', "
                            "or 'add-content'. It is combined with step_idx to identify the step."
                        ),
                    },
                ),
                "image_name": (
                    "STRING",
                    {
                        "default": "image",
                        "tooltip": (
                            "Base filename used for candidate PNG and JSON files. Run and candidate "
                            "identifiers are appended automatically."
                        ),
                    },
                ),
                "storage_root": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "Optional absolute root folder for all Iterative Image Toolkit projects. "
                            "Leave blank to use ComfyUI/output/iterative-image-toolkit."
                        ),
                    },
                ),
            },
            "optional": {
                "input_mask": (
                    "MASK",
                    {
                        "tooltip": (
                            "Optional mask associated with the input image for this run. It is saved "
                            "once with the run and restored when a candidate from the run is loaded."
                        )
                    },
                ),
                "positive_prompt": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "Optional positive prompt used to create this run. It is stored in each "
                            "candidate's metadata and can be restored by IIT Load Version."
                        ),
                    },
                ),
                "negative_prompt": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "Optional negative prompt used to create this run. It is stored in each "
                            "candidate's metadata and can be restored by IIT Load Version."
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "Optional generation seed associated with this run. It is stored with "
                            "each candidate so the selected version can restore the seed later."
                        ),
                    },
                ),
                "input_image_name": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "Optional name or reference of the image used as this step's input. "
                            "This is metadata for tracing the candidate's source; it does not load a file."
                        ),
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = (
        "images",
        "input_mask",
        "positive_prompt",
        "negative_prompt",
        "seed",
        "run_json",
    )
    OUTPUT_TOOLTIPS = (
        "The original image batch, passed through unchanged for previewing or further processing.",
        (
            "The optional input mask, passed through unchanged. If no mask was supplied, this returns "
            "an empty mask matching the image batch dimensions."
        ),
        "The positive prompt supplied to this node, or an empty string when it was not connected.",
        "The negative prompt supplied to this node, or an empty string when it was not connected.",
        "The seed supplied to this node, or -1 when no seed was connected.",
        (
            "A JSON string describing the saved project, step, run ID, and all candidates created "
            "during this execution."
        ),
    )
    FUNCTION = "save"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Saves one generated image batch as a versioned candidate run. Each queue execution becomes "
        "one run, while each image in the batch becomes an individual candidate. Candidate PNG files, "
        "sidecar JSON metadata, optional prompts, seed, mask, and source image name are recorded under "
        "the selected project and step. This node only records candidates; use IIT Load Version's "
        "Version Browser to accept a candidate or promote it to the next step."
    )

    def save(
        self,
        images: torch.Tensor,
        project_name: str,
        step_idx: int,
        step_name: str,
        image_name: str,
        storage_root: str = "",
        input_mask: torch.Tensor | None = None,
        positive_prompt: str = "",
        negative_prompt: str = "",
        seed: int | None = None,
        input_image_name: str = "",
        prompt: dict[str, Any] | None = None,
        extra_pnginfo: dict[str, Any] | None = None,
    ):
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        project = project_dir(root, project_name)
        project.mkdir(parents=True, exist_ok=True)

        manifest = load_manifest(project, create=True, project_name=project_name)
        from .storage import ensure_step, next_number

        key, step = ensure_step(manifest, step_idx, step_name)
        run_no = next_number(step["runs"], "run_id")
        run_id = f"run-{run_no:04d}"
        run_dir = project / key / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        safe_name = slug(image_name, "image")
        candidates: list[dict[str, Any]] = []

        mask_rel = None
        if input_mask is not None:
            mask_file = run_dir / f"{safe_name}-input-mask.png"
            save_mask(input_mask, mask_file)
            mask_rel = mask_file.relative_to(project).as_posix()

        for index, image in enumerate(images):
            candidate_id = f"{run_id}-candidate-{index + 1:03d}"
            basename = f"{safe_name}-{run_id}-candidate-{index + 1:03d}"
            image_file = run_dir / f"{basename}.png"
            sidecar_file = run_dir / f"{basename}.json"
            Image.fromarray(tensor_to_rgb(image), mode="RGB").save(
                image_file, format="PNG", compress_level=4
            )
            candidate = {
                "candidate_id": candidate_id,
                "candidate_index": index + 1,
                "created_at": utc_now(),
                "image_path": image_file.relative_to(project).as_posix(),
                "sidecar_path": sidecar_file.relative_to(project).as_posix(),
                "input_mask_path": mask_rel,
                "input_image_name": input_image_name or None,
                "positive_prompt": positive_prompt or "",
                "negative_prompt": negative_prompt or "",
                "seed": seed,
            }
            sidecar = {
                **candidate,
                "project_name": project_name,
                "step_idx": int(step_idx),
                "step_name": step_name,
                "run_id": run_id,
                "comfy_prompt": prompt,
                "extra_pnginfo": extra_pnginfo,
            }
            atomic_write_json(sidecar_file, sidecar)
            candidates.append(candidate)

        _, key, registered_run_id = register_run(
            root, project_name, step_idx, step_name, image_name, candidates
        )
        if registered_run_id != run_id:
            raise RuntimeError("Concurrent run allocation conflict; retry the queue")
        output_mask = (
            input_mask
            if input_mask is not None
            else torch.zeros(
                (images.shape[0], images.shape[1], images.shape[2]),
                dtype=images.dtype,
                device=images.device,
            )
        )
        run_json = json.dumps(
            {
                "project": project_name,
                "step_key": key,
                "run_id": run_id,
                "candidates": candidates,
            },
            ensure_ascii=False,
        )
        return (
            images,
            output_mask,
            positive_prompt or "",
            negative_prompt or "",
            int(seed) if seed is not None else -1,
            run_json,
        )


class IITLoadVersion:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_name": (
                    "STRING",
                    {
                        "default": "my-project",
                        "tooltip": (
                            "Name of the existing Iterative Image Toolkit project to load. It must "
                            "match the project_name used by IIT Save Candidate Run."
                        ),
                    },
                ),
                "step_key": (
                    "STRING",
                    {
                        "default": "01-edit",
                        "tooltip": (
                            "Exact step identifier to load, formatted as the zero-padded step index "
                            "plus the sanitized step name, for example '01-color'."
                        ),
                    },
                ),
                "selection": (
                    ["current", "candidate"],
                    {
                        "tooltip": (
                            "Choose 'current' to load the candidate referenced by this step's accepted "
                            "current version. Choose 'candidate' to load the exact candidate_id below."
                        )
                    },
                ),
                "candidate_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "Exact candidate identifier, such as 'run-0003-candidate-002'. This field "
                            "is required only when selection is set to 'candidate'."
                        ),
                    },
                ),
                "storage_root": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "Optional absolute root folder containing the project. Leave blank to use "
                            "ComfyUI/output/iterative-image-toolkit. Use the same root used when saving."
                        ),
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = (
        "image",
        "mask",
        "positive_prompt",
        "negative_prompt",
        "seed",
        "metadata_json",
    )
    OUTPUT_TOOLTIPS = (
        "The RGB image stored for the resolved current version or requested candidate.",
        (
            "The mask associated with the candidate's original run. If no saved mask exists, this "
            "returns the mask encoded in the image alpha channel or an empty mask."
        ),
        "The positive prompt saved with the selected candidate, or an empty string if none was recorded.",
        "The negative prompt saved with the selected candidate, or an empty string if none was recorded.",
        "The seed saved with the selected candidate, or -1 if no seed was recorded.",
        (
            "A formatted JSON string containing the selected candidate's IDs, file references, prompts, "
            "seed, source image name, project name, and step key."
        ),
    )
    FUNCTION = "load"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Loads an accepted current version or a specific saved candidate from one project step, together "
        "with its associated mask, positive prompt, negative prompt, seed, and metadata. Use the node's "
        "Open Version Browser button to compare candidates, set one as the current version, promote it to "
        "the next step, or stage it for ComfyUI's native Mask Editor."
    )

    def load(
        self,
        project_name: str,
        step_key: str,
        selection: str,
        candidate_id: str,
        storage_root: str = "",
    ):
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        project = project_dir(root, project_name)
        manifest = load_manifest(project)
        step = find_step(manifest, step_key)
        resolved_id = resolve_selection(step, selection, candidate_id)
        candidate = find_candidate(manifest, step, resolved_id)
        image, alpha_mask = load_image_and_mask(candidate_path(project, candidate))
        mask_path = candidate.get("input_mask_path")
        if mask_path:
            mask_file = project / mask_path
            if mask_file.exists():
                mask_array = np.asarray(
                    Image.open(mask_file).convert("L"), dtype=np.float32
                ) / 255.0
                alpha_mask = torch.from_numpy(mask_array).unsqueeze(0)
        metadata = dict(candidate)
        metadata.update({"project_name": project_name, "step_key": step_key})
        return (
            image,
            alpha_mask,
            candidate.get("positive_prompt") or "",
            candidate.get("negative_prompt") or "",
            int(candidate["seed"]) if candidate.get("seed") is not None else -1,
            json.dumps(metadata, ensure_ascii=False, indent=2),
        )

    @classmethod
    def IS_CHANGED(
        cls,
        project_name: str,
        step_key: str,
        selection: str,
        candidate_id: str,
        storage_root: str = "",
    ):
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        project = project_dir(root, project_name)
        manifest_file = project / "project.json"
        return (
            f"{manifest_file.stat().st_mtime_ns if manifest_file.exists() else 0}:"
            f"{selection}:{candidate_id}"
        )


class IITLocateEditedCrop:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_a": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "The larger source image in which to locate image B. Its mostly unchanged "
                            "background should still be visible in image B for reliable matching."
                        )
                    },
                ),
                "image_b": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "The smaller edited crop to locate inside image A. Translation, uniform scale, "
                            "rotation, recoloring, and small local edits or object movements are allowed."
                        )
                    },
                ),
            }
        }

    RETURN_TYPES = ("BBOX", "ROTATED_BBOX", "IMAGE", "FLOAT", "IMAGE", "STRING")
    RETURN_NAMES = (
        "axis_bbox",
        "rotated_bbox",
        "aligned_crop",
        "confidence",
        "diagnostic_heatmap",
        "diagnostics_json",
    )
    OUTPUT_TOOLTIPS = (
        (
            "Axis-aligned bounding box of image B's estimated location in image A. The object contains "
            "x, y, width, height, x1, y1, x2, and y2 in image-A pixel coordinates."
        ),
        (
            "Rotation-aware quadrilateral describing image B's estimated footprint in image A. It contains "
            "four corner coordinates, center, uniform scale, and rotation in degrees."
        ),
        (
            "The matching region sampled from image A and transformed into image B's width, height, and "
            "orientation. Use it to compare the original source region directly with edited image B."
        ),
        (
            "Heuristic match-quality score from 0.0 to 1.0. Higher values indicate stronger feature agreement, "
            "better spatial coverage, lower residual flow, and a crop that lies inside image A. It is not a probability."
        ),
        (
            "Color diagnostic image in image B's dimensions. Cooler regions generally agree after alignment; "
            "warmer regions indicate larger optical-flow or edge differences, such as moved or inpainted content."
        ),
        (
            "A formatted JSON string containing the algorithm name, match and inlier counts, feature coverage, "
            "median flow, transform matrix, both bounding boxes, and confidence score."
        ),
    )
    FUNCTION = "locate"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Finds where a smaller edited crop (image B) came from inside a larger source image (image A). It "
        "estimates translation, uniform scale, and rotation from robust background feature matches, then uses "
        "optical flow for residual-change diagnostics. Small local inpainting or object movement is treated as "
        "an outlier rather than requiring every pixel to remain unchanged."
    )

    def locate(self, image_a: torch.Tensor, image_b: torch.Tensor):
        results = []
        batch = max(len(image_a), len(image_b))
        for index in range(batch):
            a = tensor_to_rgb(image_a[min(index, len(image_a) - 1)])
            b = tensor_to_rgb(image_b[min(index, len(image_b) - 1)])
            results.append(locate_crop(a, b))
        aligned = torch.cat(
            [numpy_to_tensor(item.aligned_crop) for item in results], dim=0
        )
        heatmaps = torch.cat(
            [numpy_to_tensor(item.heatmap) for item in results], dim=0
        )
        axis = (
            results[0].axis_bbox
            if len(results) == 1
            else [item.axis_bbox for item in results]
        )
        rotated = (
            results[0].rotated_bbox
            if len(results) == 1
            else [item.rotated_bbox for item in results]
        )
        confidence = float(min(item.confidence for item in results))
        diagnostics = (
            diagnostics_json(results[0])
            if len(results) == 1
            else json.dumps(
                [item.diagnostics for item in results],
                ensure_ascii=False,
                indent=2,
            )
        )
        return (axis, rotated, aligned, confidence, heatmaps, diagnostics)


NODE_CLASS_MAPPINGS = {
    "IITSaveCandidates": IITSaveCandidates,
    "IITLoadVersion": IITLoadVersion,
    "IITLocateEditedCrop": IITLocateEditedCrop,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IITSaveCandidates": "IIT Save Candidate Run",
    "IITLoadVersion": "IIT Load Version",
    "IITLocateEditedCrop": "IIT Locate Edited Crop",
}
