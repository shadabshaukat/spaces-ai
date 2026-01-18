#!/usr/bin/env bash
set -euo pipefail
# Run SpacesAI in the foreground on a VM using uv
# Honors HOST/PORT/WORKERS from .env

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo ".venv not found; running build to install dependencies..."
  ./build-app.sh
fi

exec uv run searchapp
