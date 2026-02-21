#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname \"$0\")"

# Load .env if present for local convenience
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

# Install dependencies including optional PDF/Office/Vision/Image/Caption extras for robust multimodal ingest
uv sync --extra pdf --extra office --extra vision --extra audio --extra image --extra caption
uv run searchapp
