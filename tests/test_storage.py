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
