#!/usr/bin/env bash
set -euo pipefail
# Start SpacesAI in the background on a VM using uv (nohup)
# Writes PID file to .pids/searchapp.pid

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$SCRIPT_DIR"

mkdir -p .pids
PID_FILE=.pids/searchapp.pid

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "SpacesAI already running with PID $(cat "$PID_FILE")"
  exit 0
fi

if [ ! -d ".venv" ]; then
  echo ".venv not found; running build to install dependencies..."
  ./build-app.sh
fi

nohup uv run searchapp > spacesai.out 2>&1 &
echo $! > "$PID_FILE"
echo "SpacesAI started with PID $(cat "$PID_FILE")"
