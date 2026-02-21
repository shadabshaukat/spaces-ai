#!/usr/bin/env bash
set -euo pipefail
# Start SpacesAI in the background on a VM using uv (nohup)
# Writes PID file to .pids/searchapp.pid

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$SCRIPT_DIR"

# Load .env if present so HOST/PORT/etc. are applied consistently
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

mkdir -p .pids
PID_FILE=.pids/searchapp.pid

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "SpacesAI already running with PID $(cat "$PID_FILE")"
  exit 0
fi

if [ ! -d ".venv" ]; then
  echo ".venv not found; running build to install dependencies..."
  ./build-app.sh
else
  uv sync --extra pdf --extra office --extra vision --extra audio --extra image --extra caption
fi

nohup uv run searchapp > spacesai.out 2>&1 &
echo $! > "$PID_FILE"
echo "SpacesAI started with PID $(cat "$PID_FILE")"