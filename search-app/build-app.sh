#!/usr/bin/env bash
set -euo pipefail
# Build the SpacesAI container image
# Env:
#   IMAGE_NAME (default: spacesai:latest)
IMAGE_NAME=${IMAGE_NAME:-spacesai:latest}
# Build from repo root so Dockerfile path resolves
ROOT_DIR=$(cd "$(dirname "$0")/.."; pwd)
cd "$ROOT_DIR"

docker build -f search-app/Dockerfile -t "$IMAGE_NAME" .

echo "Built $IMAGE_NAME"
