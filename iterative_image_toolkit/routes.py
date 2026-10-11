from __future__ import annotations

import folder_paths
from aiohttp import web
from server import PromptServer

from .storage import (
    accept_candidate,
    build_trajectory,
    candidate_path,
    copy_to_input,
    find_candidate,
    find_step,
    load_manifest,
    project_dir,
    resolve_storage_root,
)

routes = PromptServer.instance.routes


def context(storage_root: str, project_name: str):
    root = resolve_storage_root(storage_root, folder_paths.get_output_directory())
    project = project_dir(root, project_name)
    return root, project


def error_response(exc: Exception, status: int = 400):
    return web.json_response({"error": str(exc), "type": type(exc).__name__}, status=status)


@routes.get("/iit/manifest")
async def get_manifest(request):
    try:
        _, project = context(request.query.get("storage_root", ""), request.query["project_name"])
        return web.json_response(load_manifest(project))
    except Exception as exc:
        return error_response(exc, 404 if isinstance(exc, FileNotFoundError) else 400)


@routes.get("/iit/trajectory")
async def get_trajectory(request):
    try:
        _, project = context(request.query.get("storage_root", ""), request.query["project_name"])
        return web.json_response(build_trajectory(load_manifest(project)))
    except Exception as exc:
        return error_response(exc, 404 if isinstance(exc, FileNotFoundError) else 400)


@routes.get("/iit/initial-image")
async def get_initial_image(request):
    try:
        _, project = context(request.query.get("storage_root", ""), request.query["project_name"])
        manifest = load_manifest(project)
        image_name = (manifest.get("initial_input") or {}).get("image")
        if not image_name:
            raise FileNotFoundError("Initial image is not recorded for this project")
        path = folder_paths.get_annotated_filepath(image_name)
        if not path:
            raise FileNotFoundError(f"Initial image not found: {image_name}")
        return web.FileResponse(path)
    except Exception as exc:
        return error_response(exc, 404)


@routes.get("/iit/image")
async def get_candidate_image(request):
    try:
        _, project = context(request.query.get("storage_root", ""), request.query["project_name"])
        manifest = load_manifest(project)
        step = find_step(manifest, request.query["step_key"])
        candidate = find_candidate(manifest, step, request.query["candidate_id"])
        return web.FileResponse(candidate_path(project, candidate))
    except Exception as exc:
        return error_response(exc, 404)


@routes.post("/iit/accept")
async def post_accept(request):
    try:
        body = await request.json()
        root, _ = context(body.get("storage_root", ""), body["project_name"])
        result = accept_candidate(
            root,
            body["project_name"],
            body["step_key"],
            body["candidate_id"],
            body.get("action", "set_current"),
            body.get("target_step_idx"),
            body.get("target_step_name", ""),
        )
        return web.json_response(result)
    except Exception as exc:
        return error_response(exc)


@routes.post("/iit/stage")
async def post_stage(request):
    try:
        body = await request.json()
        _, project = context(body.get("storage_root", ""), body["project_name"])
        manifest = load_manifest(project)
        step = find_step(manifest, body["step_key"])
        candidate = find_candidate(manifest, step, body["candidate_id"])
        mask_source = project / candidate["input_mask_path"] if candidate.get("input_mask_path") else None
        relative = copy_to_input(
            candidate_path(project, candidate),
            folder_paths.get_input_directory(),
            body["project_name"],
            mask_source,
        )
        return web.json_response({"image": relative})
    except Exception as exc:
        return error_response(exc)
