from __future__ import annotations

import hashlib
import json
import os
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
    step_key as make_step_key,
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
                    {"tooltip": "Image batch to save. One queue execution creates one run; each batch image becomes a candidate."},
                ),
                "project_name": (
                    "STRING",
                    {
                        "default": "my-project",
                        "tooltip": "Fallback project name used only when iit_meta is not connected. Connected IIT_META overrides and disables this widget.",
                    },
                ),
                "step_idx": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 9999,
                        "tooltip": "Fallback step number used only when iit_meta is not connected. Connected IIT_META overrides and disables this widget.",
                    },
                ),
                "step_name": (
                    "STRING",
                    {
                        "default": "edit",
                        "tooltip": "Fallback step name used only when iit_meta is not connected. Connected IIT_META overrides and disables this widget.",
                    },
                ),
                "image_name": (
                    "STRING",
                    {
                        "default": "image",
                        "tooltip": "Base filename for candidate PNG and JSON files. Run/candidate identifiers are appended. IIT_META does not override this field.",
                    },
                ),
                "storage_root": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Fallback storage root used only without iit_meta. Blank uses ComfyUI/output/iterative-image-toolkit. Connected IIT_META overrides it.",
                    },
                ),
            },
            "optional": {
                "iit_meta": (
                    "IIT_META",
                    {
                        "tooltip": "Project context from IIT Load Version. When connected, project_name, step_idx, step_name, step_key and storage_root override the fallback widgets."
                    },
                ),
                "input_mask": (
                    "MASK",
                    {"tooltip": "Optional mask associated with this run. It is saved once and restored when a candidate from the run is loaded."},
                ),
                "positive_prompt": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Optional positive prompt stored in each candidate. Connect IIT Load Version to preserve manual or restored metadata.",
                    },
                ),
                "negative_prompt": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Optional negative prompt stored in each candidate. Connect IIT Load Version to preserve manual or restored metadata.",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "forceInput": True,
                        "tooltip": "Optional generation seed stored in each candidate. Connect IIT Load Version to preserve manual or restored metadata.",
                    },
                ),
                "input_image_name": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Optional source-image name for traceability. This metadata field does not load a file.",
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("images", "input_mask", "positive_prompt", "negative_prompt", "seed", "run_json")
    OUTPUT_TOOLTIPS = (
        "Original image batch passed through unchanged.",
        "Connected input mask, or an empty mask matching the image batch when no mask was supplied.",
        "Connected positive prompt, or an empty string.",
        "Connected negative prompt, or an empty string.",
        "Connected seed, or -1 when absent.",
        "JSON describing the effective project/step, run ID and candidates created by this execution.",
    )
    FUNCTION = "save"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Saves a generated image batch as a versioned candidate run without overwriting earlier candidates. "
        "Each queue is one run and each batch image is one candidate. Connect IIT_META from IIT Load Version "
        "to reuse the same project and step automatically; otherwise the local project widgets are used."
    )

    @staticmethod
    def _project_context(project_name, step_idx, step_name, storage_root, iit_meta):
        if iit_meta is None:
            return project_name, int(step_idx), step_name, storage_root, make_step_key(step_idx, step_name)
        if not isinstance(iit_meta, dict):
            raise TypeError("iit_meta must be an IIT_META object produced by IIT Load Version")
        required = {"project_name", "step_idx", "step_name", "step_key", "storage_root"}
        missing = sorted(required.difference(iit_meta))
        if missing:
            raise ValueError(f"iit_meta is missing required fields: {', '.join(missing)}")
        idx = int(iit_meta["step_idx"])
        name = str(iit_meta["step_name"])
        expected = make_step_key(idx, name)
        if str(iit_meta["step_key"]) != expected:
            raise ValueError(f"iit_meta step_key {iit_meta['step_key']!r} does not match step_idx/step_name ({expected!r})")
        return str(iit_meta["project_name"]), idx, name, str(iit_meta["storage_root"] or ""), expected

    def save(
        self,
        images: torch.Tensor,
        project_name: str,
        step_idx: int,
        step_name: str,
        image_name: str,
        storage_root: str = "",
        iit_meta: dict[str, Any] | None = None,
        input_mask: torch.Tensor | None = None,
        positive_prompt: str = "",
        negative_prompt: str = "",
        seed: int | None = None,
        input_image_name: str = "",
        prompt: dict[str, Any] | None = None,
        extra_pnginfo: dict[str, Any] | None = None,
    ):
        project_name, step_idx, step_name, storage_root, expected_key = self._project_context(
            project_name, step_idx, step_name, storage_root, iit_meta
        )
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        project = project_dir(root, project_name)
        manifest, key, run_id = register_run(root, project_name, step_idx, step_name, image_name, [])
        if key != expected_key:
            raise RuntimeError(f"Resolved step key changed unexpectedly: {key} != {expected_key}")
        step = find_step(manifest, key)
        run = next(item for item in step["runs"] if item["run_id"] == run_id)
        run_dir = project / key / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        mask_rel = None
        if input_mask is not None:
            mask_rel = str((Path(key) / "runs" / run_id / f"{slug(image_name)}-input-mask.png").as_posix())
            save_mask(input_mask, project / mask_rel)
        candidates = []
        arrays = tensor_to_rgb(images)
        if arrays.ndim == 3:
            arrays = arrays[None, ...]
        for index, array in enumerate(arrays, start=1):
            candidate_id = f"{run_id}-candidate-{index:03d}"
            stem = f"{slug(image_name)}-{run_id}-candidate-{index:03d}"
            image_rel = Path(key) / "runs" / run_id / f"{stem}.png"
            json_rel = image_rel.with_suffix(".json")
            Image.fromarray(array, mode="RGB").save(project / image_rel, format="PNG")
            candidate = {
                "candidate_id": candidate_id,
                "created_at": utc_now(),
                "image_path": image_rel.as_posix(),
                "sidecar_path": json_rel.as_posix(),
                "input_mask_path": mask_rel,
                "input_image_name": input_image_name or None,
                "positive_prompt": positive_prompt or None,
                "negative_prompt": negative_prompt or None,
                "seed": int(seed) if seed is not None else None,
                "batch_index": index - 1,
                "workflow_prompt": prompt,
                "extra_pnginfo": extra_pnginfo,
            }
            atomic_write_json(project / json_rel, candidate)
            candidates.append(candidate)
        run["candidates"] = candidates
        atomic_write_json(project / "project.json", manifest)
        output_mask = (
            torch.zeros((images.shape[0], images.shape[1], images.shape[2]), dtype=torch.float32, device=images.device)
            if input_mask is None
            else input_mask
        )
        run_json = json.dumps(
            {"project_name": project_name, "step_key": key, "run_id": run_id, "candidates": candidates},
            ensure_ascii=False,
        )
        return images, output_mask, positive_prompt or "", negative_prompt or "", int(seed) if seed is not None else -1, run_json


class IITLoadVersion:
    SOURCE_INITIAL = "initial_image"
    SOURCE_CURRENT = "current_version"
    SOURCE_CANDIDATE = "candidate"

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        if os.path.isdir(input_dir):
            files = [name for name in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, name))]
            filter_images = getattr(folder_paths, "filter_files_content_types", None)
            if filter_images is not None:
                files = filter_images(files, ["image"])
        return {
            "required": {
                "image": (
                    sorted(files),
                    {
                        "image_upload": True,
                        "tooltip": "Initial image from ComfyUI input. Upload/select it like Load Image. Used only in initial_image mode and compatible with the native Mask Editor image widget.",
                    },
                ),
                "project_name": (
                    "STRING",
                    {"default": "my-project", "tooltip": "Project name used for loading saved versions and emitted in IIT_META for IIT Save Candidate Run."},
                ),
                "step_idx": (
                    "INT",
                    {"default": 1, "min": 1, "max": 9999, "tooltip": "Numeric step order. Combined with step_name to form step_key and emitted in IIT_META."},
                ),
                "step_name": (
                    "STRING",
                    {"default": "edit", "tooltip": "Human-readable step name. Combined with step_idx to form step_key and emitted in IIT_META."},
                ),
                "source": (
                    [cls.SOURCE_INITIAL, cls.SOURCE_CURRENT, cls.SOURCE_CANDIDATE],
                    {
                        "tooltip": "Selects one coherent source for image, mask, prompts and seed. Initial uses this node's image/manual fields; current_version restores the accepted candidate; candidate restores candidate_id."
                    },
                ),
                "candidate_id": (
                    "STRING",
                    {"default": "", "tooltip": "Exact ID such as run-0003-candidate-002. Used and enabled only when source is candidate."},
                ),
                "positive_prompt": (
                    "STRING",
                    {"default": "", "multiline": True, "tooltip": "Manual positive prompt used only in initial_image mode. Saved-source modes restore candidate metadata instead."},
                ),
                "negative_prompt": (
                    "STRING",
                    {"default": "", "multiline": True, "tooltip": "Manual negative prompt used only in initial_image mode. Saved-source modes restore candidate metadata instead."},
                ),
                "seed": (
                    "INT",
                    {"default": -1, "min": -1, "max": 0x7FFFFFFFFFFFFFFF, "tooltip": "Manual seed used only in initial_image mode. Use -1 if unknown; saved-source modes restore candidate metadata."},
                ),
                "storage_root": (
                    "STRING",
                    {"default": "", "tooltip": "Project storage root emitted in IIT_META. Blank uses ComfyUI/output/iterative-image-toolkit."},
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "INT", "STRING", "IIT_META")
    RETURN_NAMES = ("image", "mask", "positive_prompt", "negative_prompt", "seed", "metadata_json", "iit_meta")
    OUTPUT_TOOLTIPS = (
        "Initial image or saved candidate selected by source.",
        "Initial alpha/Mask Editor mask or the selected candidate run's saved mask; empty when none exists.",
        "Manual positive prompt in initial mode, otherwise the restored candidate prompt.",
        "Manual negative prompt in initial mode, otherwise the restored candidate prompt.",
        "Manual seed in initial mode, otherwise the restored candidate seed or -1.",
        "Formatted JSON describing the resolved image/metadata source.",
        "Project context for IIT Save Candidate Run: schema_version, project_name, step_idx, step_name, step_key and storage_root.",
    )
    FUNCTION = "load"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Replaces Load Image for an iterative project step. Begin by uploading/selecting an initial image and entering optional multiline prompts and a seed. "
        "Later switch source to the current accepted version or a candidate to restore its image, mask, prompts and seed together. IIT_META carries the same project/step to IIT Save Candidate Run."
    )

    @staticmethod
    def _meta(project_name, step_idx, step_name, storage_root):
        return {
            "schema_version": 1,
            "project_name": project_name,
            "step_idx": int(step_idx),
            "step_name": step_name,
            "step_key": make_step_key(step_idx, step_name),
            "storage_root": storage_root or "",
        }

    @staticmethod
    def _initial_image_path(image):
        return Path(folder_paths.get_annotated_filepath(image))

    def load(self, image, project_name, step_idx, step_name, source, candidate_id, positive_prompt, negative_prompt, seed, storage_root=""):
        meta = self._meta(project_name, step_idx, step_name, storage_root)
        if source == self.SOURCE_INITIAL:
            loaded_image, loaded_mask = load_image_and_mask(self._initial_image_path(image))
            metadata = {
                "source": source,
                "image": image,
                "positive_prompt": positive_prompt or "",
                "negative_prompt": negative_prompt or "",
                "seed": int(seed),
                **meta,
            }
            return loaded_image, loaded_mask, positive_prompt or "", negative_prompt or "", int(seed), json.dumps(metadata, ensure_ascii=False, indent=2), meta
        if source not in {self.SOURCE_CURRENT, self.SOURCE_CANDIDATE}:
            raise ValueError(f"Unknown source: {source}")
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        project = project_dir(root, project_name)
        manifest = load_manifest(project)
        step = find_step(manifest, meta["step_key"])
        resolved_id = resolve_selection(step, "current" if source == self.SOURCE_CURRENT else "candidate", candidate_id)
        candidate = find_candidate(manifest, step, resolved_id)
        loaded_image, loaded_mask = load_image_and_mask(candidate_path(project, candidate))
        mask_path = candidate.get("input_mask_path")
        if mask_path and (project / mask_path).exists():
            mask_array = np.asarray(Image.open(project / mask_path).convert("L"), dtype=np.float32) / 255.0
            loaded_mask = torch.from_numpy(mask_array).unsqueeze(0)
        metadata = dict(candidate)
        metadata.update({"source": source, **meta})
        return (
            loaded_image,
            loaded_mask,
            candidate.get("positive_prompt") or "",
            candidate.get("negative_prompt") or "",
            int(candidate["seed"]) if candidate.get("seed") is not None else -1,
            json.dumps(metadata, ensure_ascii=False, indent=2),
            meta,
        )

    @classmethod
    def IS_CHANGED(cls, image, project_name, step_idx, step_name, source, candidate_id, positive_prompt, negative_prompt, seed, storage_root=""):
        if source == cls.SOURCE_INITIAL:
            digest = hashlib.sha256()
            with cls._initial_image_path(image).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            for value in (positive_prompt, negative_prompt, project_name, str(int(step_idx)), step_name, storage_root, str(int(seed))):
                digest.update((value or "").encode("utf-8"))
            return digest.hexdigest()
        root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
        manifest_file = project_dir(root, project_name) / "project.json"
        return f"{manifest_file.stat().st_mtime_ns if manifest_file.exists() else 0}:{make_step_key(step_idx, step_name)}:{source}:{candidate_id}"

    @classmethod
    def VALIDATE_INPUTS(cls, image, project_name, step_idx, step_name, source, candidate_id, positive_prompt, negative_prompt, seed, storage_root=""):
        if source == cls.SOURCE_INITIAL:
            exists = getattr(folder_paths, "exists_annotated_filepath", None)
            if exists is not None and not exists(image):
                return f"Invalid initial image file: {image}"
            return True
        if source == cls.SOURCE_CANDIDATE and not candidate_id.strip():
            return "candidate_id is required when source is 'candidate'"
        if source not in {cls.SOURCE_CURRENT, cls.SOURCE_CANDIDATE}:
            return f"Unknown source: {source}"
        return True


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
