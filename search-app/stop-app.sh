#!/usr/bin/env bash
set -euo pipefail
# Stop SpacesAI background process started by start-app.sh

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$SCRIPT_DIR"

PID_FILE=.pids/searchapp.pid
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" || true
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
      echo "Process still running; sending SIGKILL"
      kill -9 "$PID" || true
    fi
    rm -f "$PID_FILE"
    echo "SpacesAI stopped."
    exit 0
  else
    echo "No running process found with PID $PID; cleaning up PID file."
    rm -f "$PID_FILE"
  fi
fi

# Fallback: try pkill on uv/uvicorn
pkill -f "uv run searchapp|app.main:app|uvicorn" || true
echo "Stop attempt complete."
