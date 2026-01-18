# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/root/.local/bin:${PATH}"

# System packages for OCR/AV and build
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential tesseract-ocr ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
# Copy project metadata first for layer caching
COPY search-app/pyproject.toml ./pyproject.toml
# Create virtual env and sync dependencies with extras
RUN uv sync --python 3.11 --extra pdf --extra office --extra vision --extra audio

# Copy source
COPY search-app /app

# Expose and default envs
ENV HOST=0.0.0.0 PORT=8000 WORKERS=2
EXPOSE 8000

# Run the app (uv run uses .venv created by uv sync)
CMD ["uv", "run", "searchapp"]
