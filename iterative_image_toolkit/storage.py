from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._ -]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str, fallback: str = "untitled") -> str:
    cleaned = _SAFE_COMPONENT.sub("-", str(value)).strip(" .-")
    cleaned = re.sub(r"[ .-]+", "-", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned[:96]


def resolve_storage_root(storage_root: str | None, default_root: str | Path) -> Path:
    raw = (storage_root or "").strip()
    root = Path(raw).expanduser() if raw else Path(default_root) / "iterative-image-toolkit"
    return root.resolve()


def project_dir(root: str | Path, project_name: str) -> Path:
    return (Path(root).resolve() / slug(project_name, "project")).resolve()


def ensure_within(path: str | Path, parent: str | Path) -> Path:
    candidate = Path(path).resolve()
    base = Path(parent).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path escapes the permitted root: {candidate}") from exc
    return candidate


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def new_manifest(project_name: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": project_name,
        "created_at": now,
        "updated_at": now,
        "steps": {},
    }


def load_manifest(project: str | Path, create: bool = False, project_name: str = "") -> dict[str, Any]:
    path = Path(project) / "project.json"
    if not path.exists():
        if not create:
            raise FileNotFoundError(path)
        return new_manifest(project_name or Path(project).name)
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported manifest schema: {manifest.get('schema_version')}")
    return manifest


def save_manifest(project: str | Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = utc_now()
    atomic_write_json(Path(project) / "project.json", manifest)


def step_key(step_idx: int, step_name: str) -> str:
    return f"{int(step_idx):02d}-{slug(step_name, 'step')}"


def ensure_step(manifest: dict[str, Any], step_idx: int, step_name: str) -> tuple[str, dict[str, Any]]:
    key = step_key(step_idx, step_name)
    steps = manifest.setdefault("steps", {})
    step = steps.setdefault(
        key,
        {
            "step_idx": int(step_idx),
            "step_name": step_name,
            "runs": [],
            "versions": [],
            "current_version_id": None,
            "input_ref": None,
        },
    )
    return key, step


def next_number(items: list[dict[str, Any]], key: str) -> int:
    values = []
    for item in items:
        value = str(item.get(key, ""))
        match = re.search(r"(\d+)$", value)
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def register_run(
    root: str | Path,
    project_name: str,
    step_idx: int,
    step_name: str,
    image_name: str,
    candidates: list[dict[str, Any]],
    initial_input: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    root_path = Path(root).resolve()
    project = project_dir(root_path, project_name)
    project.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        manifest = load_manifest(project, create=True, project_name=project_name)
        if initial_input and not manifest.get("initial_input"):
            manifest["initial_input"] = initial_input
        key, step = ensure_step(manifest, step_idx, step_name)
        run_no = next_number(step["runs"], "run_id")
        run_id = f"run-{run_no:04d}"
        run_rel = Path(key) / "runs" / run_id
        run_dir = ensure_within(project / run_rel, project)
        run_dir.mkdir(parents=True, exist_ok=True)
        run = {
            "run_id": run_id,
            "created_at": utc_now(),
            "image_name": image_name,
            "candidates": candidates,
        }
        step["runs"].append(run)
        save_manifest(project, manifest)
    return manifest, key, run_id


def find_candidate(manifest: dict[str, Any], step: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for run in step.get("runs", []):
        for candidate in run.get("candidates", []):
            if candidate.get("candidate_id") == candidate_id:
                return candidate
    raise KeyError(f"Candidate not found: {candidate_id}")


def find_step(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    try:
        return manifest["steps"][key]
    except KeyError as exc:
        raise KeyError(f"Step not found: {key}") from exc


def resolve_selection(step: dict[str, Any], selection: str, candidate_id: str = "") -> str:
    if selection == "candidate":
        if not candidate_id:
            raise ValueError("candidate_id is required for candidate selection")
        return candidate_id
    version_id = step.get("current_version_id") if selection == "current" else selection
    if not version_id:
        raise ValueError("No accepted/current version is available")
    version = next((item for item in step.get("versions", []) if item.get("version_id") == version_id), None)
    if not version:
        raise KeyError(f"Version not found: {version_id}")
    return str(version["accepted_candidate_id"])


def find_version(step: dict[str, Any], version_id: str) -> dict[str, Any]:
    version = next((item for item in step.get("versions", []) if item.get("version_id") == version_id), None)
    if not version:
        raise KeyError(f"Version not found: {version_id}")
    return version


def resolve_promoted_selection(manifest: dict[str, Any], step: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = step.get("input_ref")
    if not ref:
        raise ValueError("This step has no promoted input")
    source_step = find_step(manifest, str(ref["step_key"]))
    candidate = find_candidate(manifest, source_step, str(ref["candidate_id"]))
    return source_step, candidate


def accept_candidate(
    root: str | Path,
    project_name: str,
    step_key_value: str,
    candidate_id: str,
    action: str,
    target_step_idx: int | None = None,
    target_step_name: str = "",
) -> dict[str, Any]:
    project = project_dir(root, project_name)
    with _LOCK:
        manifest = load_manifest(project)
        step = find_step(manifest, step_key_value)
        find_candidate(manifest, step, candidate_id)
        current_id = step.get("current_version_id")
        current = find_version(step, current_id) if current_id else None
        if current and current.get("accepted_candidate_id") == candidate_id:
            version = current
            version_id = str(current_id)
        else:
            version_no = next_number(step.get("versions", []), "version_id")
            version_id = f"ver-{version_no:02d}"
            version = {
                "version_id": version_id,
                "accepted_candidate_id": candidate_id,
                "accepted_at": utc_now(),
            }
            step.setdefault("versions", []).append(version)
            step["current_version_id"] = version_id
        result = {"version_id": version_id, "manifest": manifest}
        if action == "promote":
            if target_step_idx is None:
                target_step_idx = int(step["step_idx"]) + 1
            target_name = target_step_name.strip() or f"step-{target_step_idx}"
            target_key, target = ensure_step(manifest, target_step_idx, target_name)
            target["input_ref"] = {
                "step_key": step_key_value,
                "version_id": version_id,
                "candidate_id": candidate_id,
                "promoted_at": utc_now(),
            }
            version["promoted_to_step_key"] = target_key
            result["target_step"] = {
                "step_idx": int(target["step_idx"]),
                "step_name": str(target["step_name"]),
                "step_key": target_key,
            }
        elif action != "set_current":
            raise ValueError(f"Unknown action: {action}")
        save_manifest(project, manifest)
    return result


def build_trajectory(manifest: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    initial = manifest.get("initial_input")
    if initial:
        entries.append({"kind": "initial", "status": "initial", **initial})
    else:
        entries.append({"kind": "initial", "status": "missing", "image": None})
    steps = sorted(
        manifest.get("steps", {}).items(),
        key=lambda item: (int(item[1].get("step_idx", 0)), item[0]),
    )
    referenced_versions: dict[str, tuple[str, str]] = {}
    for destination_key, destination in steps:
        ref = destination.get("input_ref") or {}
        if ref.get("step_key") and ref.get("version_id"):
            referenced_versions[str(ref["step_key"])] = (
                str(ref["version_id"]),
                destination_key,
            )
    for key, step in steps:
        referenced = referenced_versions.get(key)
        if referenced:
            version_id, promoted_to = referenced
            status = "promoted"
        else:
            version_id = step.get("current_version_id")
            promoted_to = None
            status = "pending"
        if not version_id:
            continue
        version = find_version(step, str(version_id))
        candidate = find_candidate(manifest, step, str(version["accepted_candidate_id"]))
        entries.append(
            {
                "kind": "version",
                "status": status,
                "step_key": key,
                "step_idx": int(step.get("step_idx", 0)),
                "step_name": str(step.get("step_name", "")),
                "version_id": str(version_id),
                "candidate_id": str(version["accepted_candidate_id"]),
                "run_id": str(candidate.get("candidate_id", "")).split("-candidate-")[0],
                "seed": candidate.get("seed"),
                "positive_prompt": candidate.get("positive_prompt") or "",
                "negative_prompt": candidate.get("negative_prompt") or "",
                "accepted_at": version.get("accepted_at"),
                "promoted_to_step_key": promoted_to,
            }
        )
    return {
        "project_name": manifest.get("project_name", ""),
        "entries": entries,
    }


def candidate_path(project: str | Path, candidate: dict[str, Any]) -> Path:
    return ensure_within(Path(project) / candidate["image_path"], project)


def copy_to_input(source: str | Path, input_root: str | Path, project_name: str, mask_source: str | Path | None = None) -> str:
    from PIL import Image

    source_path = Path(source)
    target_dir = Path(input_root) / "iterative-image-toolkit" / slug(project_name, "project")
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(source_path.resolve()).encode()).hexdigest()[:12]
    target_name = f"{source_path.stem}-{digest}.png"
    target = target_dir / target_name
    image = Image.open(source_path).convert("RGBA")
    if mask_source and Path(mask_source).exists():
        mask = Image.open(mask_source).convert("L").resize(image.size)
        alpha = mask.point(lambda value: 255 - value)
        image.putalpha(alpha)
    image.save(target, format="PNG")
    return target.relative_to(input_root).as_posix()
