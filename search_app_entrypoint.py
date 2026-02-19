from __future__ import annotations

import os
import sys
from pathlib import Path


def patch_path() -> None:
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    app_dir = root / "search-app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))


def get_app():
    patch_path()
    from app.main import app

    return app
