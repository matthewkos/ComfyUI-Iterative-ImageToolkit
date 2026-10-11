"""ComfyUI entrypoint with a standalone-test import fallback."""

try:
    try:
        from .iterative_image_toolkit import routes as _routes
        from .iterative_image_toolkit.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    except ImportError as relative_error:
        if "no known parent package" not in str(relative_error):
            raise
        from iterative_image_toolkit import routes as _routes  # noqa: F401
        from iterative_image_toolkit.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except (ImportError, ModuleNotFoundError) as exc:
    if getattr(exc, "name", None) not in {"folder_paths", "server", "torch"}:
        raise
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
