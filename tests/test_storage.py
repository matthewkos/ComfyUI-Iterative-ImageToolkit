import json

from iterative_image_toolkit.storage import (
    accept_candidate,
    atomic_write_json,
    load_manifest,
    project_dir,
    register_run,
    resolve_storage_root,
    slug,
)


def test_slug_blocks_traversal():
    assert ".." not in slug("../../evil")
    assert "/" not in slug("a/b")


def test_manifest_run_accept_and_promote(tmp_path):
    root = resolve_storage_root(str(tmp_path), tmp_path / "default")
    project = project_dir(root, "P α")
    candidate = {
        "candidate_id": "run-0001-candidate-001",
        "image_path": "01-color/runs/run-0001/image.png",
        "sidecar_path": "01-color/runs/run-0001/image.json",
        "positive_prompt": "warm",
        "negative_prompt": "cold",
        "seed": 42,
    }
    manifest, key, run_id = register_run(root, "P α", 1, "color", "image", [candidate])
    assert run_id == "run-0001"
    result = accept_candidate(root, "P α", key, candidate["candidate_id"], "promote", 2, "reshape")
    saved = load_manifest(project)
    assert saved["steps"][key]["current_version_id"] == "ver-01"
    assert saved["steps"]["02-reshape"]["input_ref"]["candidate_id"] == candidate["candidate_id"]
    assert result["version_id"] == "ver-01"


def test_atomic_json(tmp_path):
    path = tmp_path / "nested" / "value.json"
    atomic_write_json(path, {"hello": "世界"})
    assert json.loads(path.read_text(encoding="utf-8"))["hello"] == "世界"


def test_accept_is_idempotent_and_trajectory_marks_pending_then_promoted(tmp_path):
    from iterative_image_toolkit.storage import build_trajectory

    root = resolve_storage_root(str(tmp_path), tmp_path / "default")
    candidate = {
        "candidate_id": "run-0001-candidate-001",
        "image_path": "01-color/runs/run-0001/image.png",
        "sidecar_path": "01-color/runs/run-0001/image.json",
        "positive_prompt": "warm",
        "negative_prompt": "cold",
        "seed": 42,
    }
    manifest, key, _ = register_run(
        root,
        "project",
        1,
        "color",
        "image",
        [candidate],
        initial_input={"image": "input.png", "seed": 11},
    )
    first = accept_candidate(root, "project", key, candidate["candidate_id"], "set_current")
    second = accept_candidate(root, "project", key, candidate["candidate_id"], "set_current")
    assert first["version_id"] == second["version_id"] == "ver-01"
    manifest = load_manifest(project_dir(root, "project"))
    assert len(manifest["steps"][key]["versions"]) == 1
    assert build_trajectory(manifest)["entries"][-1]["status"] == "pending"

    promoted = accept_candidate(root, "project", key, candidate["candidate_id"], "promote", 2, "reshape")
    assert promoted["target_step"] == {"step_idx": 2, "step_name": "reshape", "step_key": "02-reshape"}
    manifest = load_manifest(project_dir(root, "project"))
    assert len(manifest["steps"][key]["versions"]) == 1
    assert build_trajectory(manifest)["entries"][-1]["status"] == "promoted"


def test_resolve_promoted_selection(tmp_path):
    from iterative_image_toolkit.storage import find_step, resolve_promoted_selection

    root = resolve_storage_root(str(tmp_path), tmp_path / "default")
    candidate = {
        "candidate_id": "run-0001-candidate-001",
        "image_path": "01-color/runs/run-0001/image.png",
        "sidecar_path": "01-color/runs/run-0001/image.json",
    }
    _, key, _ = register_run(root, "project", 1, "color", "image", [candidate])
    accept_candidate(root, "project", key, candidate["candidate_id"], "promote", 2, "reshape")
    manifest = load_manifest(project_dir(root, "project"))
    source_step, resolved = resolve_promoted_selection(manifest, find_step(manifest, "02-reshape"))
    assert source_step["step_name"] == "color"
    assert resolved["candidate_id"] == candidate["candidate_id"]
