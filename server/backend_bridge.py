"""Load the original scribd-downloader script without copying its logic.

The script file name contains a hyphen, so it cannot be imported normally.
It is loaded by path and cached for the lifetime of the process.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

_MODULE_NAME = "scribd_downloader_backend"
_DEFAULT_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scribd-downloader" / "scribd-downloader.py"
)

_module: ModuleType | None = None


def backend_script_path() -> Path:
    """Return the configured backend script path, validating that it exists."""
    configured = os.getenv("SCRIBD_BACKEND_SCRIPT", "").strip()
    path = Path(configured).expanduser() if configured else _DEFAULT_SCRIPT
    if not path.is_file():
        raise RuntimeError(f"Backend script not found: {path}")
    return path.resolve()


def load_backend() -> ModuleType:
    """Import and cache the original downloader module."""
    global _module
    if _module is None:
        path = backend_script_path()
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load backend script: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
        _module = module
    return _module


def parse_scribd_url(url: str):
    """Validate a Scribd document URL using the backend's own parser."""
    return load_backend().parse_scribd_url(url)


def get_base_name_from_url(url: str) -> str:
    """Build a safe output base name using the backend's own helper."""
    return load_backend().get_base_name_from_url(url)
