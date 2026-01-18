#!/usr/bin/env bash
set -euo pipefail
# Stop SpacesAI via Docker Compose
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.yml}
ROOT_DIR=$(cd "$(dirname "$0")/.."; pwd)
cd "$ROOT_DIR"

docker compose -f "$COMPOSE_FILE" down

echo "SpacesAI stopped."
