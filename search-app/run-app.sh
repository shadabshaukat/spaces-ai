#!/usr/bin/env bash
set -euo pipefail
# Run SpacesAI in the foreground on a VM using uv
# Honors HOST/PORT/WORKERS from .env

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$SCRIPT_DIR"

# Load .env if present to provide defaults for HOST/PORT/etc.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

DEBUG_LOGGING_DEFAULT="true"
DEBUG_LOGGING_VALUE="${DEBUG_LOGGING:-$DEBUG_LOGGING_DEFAULT}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--debug|--no-debug]

Controls the DEBUG_LOGGING environment variable (default: ${DEBUG_LOGGING_DEFAULT}).
You can also export DEBUG_LOGGING before invoking this script.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)
      DEBUG_LOGGING_VALUE="true"
      shift
      ;;
    --no-debug)
      DEBUG_LOGGING_VALUE="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

export DEBUG_LOGGING="$DEBUG_LOGGING_VALUE"

if [ ! -d ".venv" ]; then
  echo ".venv not found; running build to install dependencies..."
  ./build-app.sh
else
  uv sync --extra pdf --extra office --extra vision --extra audio --extra image --extra caption
fi

exec uv run searchapp