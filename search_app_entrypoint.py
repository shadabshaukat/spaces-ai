# Helper module to expose the FastAPI app for tests without heavy import side-effects
from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure search-app package is on sys.path
repo_root = Path(__file__).resolve().parent
search_app_dir = repo_root / "search-app"
if str(search_app_dir) not in sys.path:
    sys.path.insert(0, str(search_app_dir))

from app.main import app  # type: ignore


def patch_path() -> None:
    """Ensure repo root (parent of search-app) is on sys.path for tests."""
    repo_parent = repo_root
    if str(repo_parent) not in sys.path:
        sys.path.insert(0, str(repo_parent))


def get_app():
    return app
