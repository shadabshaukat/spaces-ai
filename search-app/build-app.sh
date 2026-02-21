#!/usr/bin/env bash
set -euo pipefail
# Build (prepare) SpacesAI on a VM: install Python deps with uv
# Usage: from repo root or search-app directory

ROOT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$ROOT_DIR"

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing to user-local..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Sync dependencies with extras for PDF/Office/Vision/Audio/Image/Captioning
uv sync --extra pdf --extra office --extra vision --extra audio --extra image --extra caption

echo "Dependencies installed. You can run the app with:"
echo "  ./run-app.sh (foreground)"
echo "  ./start-app.sh (background)"
