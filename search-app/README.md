# SpacesAI Application (FastAPI + OCI PostgreSQL + OpenSearch + Valkey)

SpacesAI is a multi-tenant, production-grade, NotebookLM-like application. Users create private Spaces, upload their own files, and run Retrieval-Augmented Generation (RAG) over multimodal content (PDF, DOCX, PPTX, XLSX, images via OCR, audio/video transcription). The stack is polyglot:

- PostgreSQL (OCI) — system-of-record for users, spaces, documents, activity
- OpenSearch (OCI) — serving backend for retrieval (KNN vectors + BM25/FTS)
- Object Storage (OCI) — binary file storage (per-user email/date prefixes)
- Valkey (OCI Cache, Redis-compatible) — caching search results
- LLM providers: OCI Generative AI, OpenAI, AWS Bedrock, and local Ollama

This README covers application setup, configuration, endpoints, and how to run locally. See the repo-level README and README_SPACESAI.md for infrastructure and architecture details.


## Features

- Multi-tenant auth with session cookies; private Spaces
- Upload → robust extractors (PDF/HTML/TXT/DOCX/PPTX/XLSX/CSV/MD/JSON/Images OCR/Audio+Video transcription)
- Chunking + embeddings; dual-write to OpenSearch for retrieval
- Retrieval: semantic (KNN), fulltext (BM25), hybrid (RRF)
- RAG over the selected Space with unified, pluggable LLM providers
- Caching via Valkey to accelerate repeated queries
- Admin APIs for listing/deleting documents and reindexing


## Requirements

- Python 3.10+
- uv package manager (https://docs.astral.sh/uv/)
- OCI PostgreSQL reachable from host
- Optional: OCI OpenSearch and OCI Cache (Valkey) endpoints (see Terraform stack)
- Optional: AWS CLI configured if using AWS Bedrock; local Ollama server if using Ollama


## Compute VM bootstrap (cloud-init)

If you deploy the optional Compute VM with the Terraform stack, cloud-init can preinstall tools required/recommended for SpacesAI. These are installed non-interactively on first boot:

Packages/tools installed
- curl, git, unzip
- firewalld (enabled, opens TCP port 8000 by default)
- oraclelinux-developer-release-el10
- python3-oci-cli
- postgresql16 (client)
- tesseract (OCR)
- ffmpeg (audio/video extraction)
- uv package manager (user-local)
- AWS CLI v2 (no credentials)
- Docker and Docker Compose (service enabled; opc added to docker group)
- Clones the repo into /home/opc/src

Equivalent commands (reference)
```bash
# OS packages
sudo dnf install -y curl git unzip firewalld oraclelinux-developer-release-el10 python3-oci-cli postgresql16 tesseract ffmpeg

# AWS CLI v2
TMPDIR=$(mktemp -d) && cd "$TMPDIR" && curl -s https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o awscliv2.zip && \
  unzip -q awscliv2.zip && sudo ./aws/install --update && cd / && rm -rf "$TMPDIR"

# uv (installer is user-local)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Docker & Docker Compose
curl -fsSL https://get.docker.com | sudo sh
sudo dnf install -y docker-compose-plugin || true
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose || true
sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose || true
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# Firewall
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload

# Clone code
mkdir -p ~/src && cd ~/src && git clone https://github.com/shadabshaukat/spaces-ai.git || true
```

Note: cloud-init runs on first boot only. If you enable or change it later, recreate the VM. Verify execution on the VM:
- sudo cloud-init status
- sudo tail -n 200 /var/log/cloud-init-output.log

## Quick Start


1) Copy and edit environment file:

```bash
ycd search-app
cp .env.example .env
# Edit DB connection and set:
#   SEARCH_BACKEND=opensearch
#   OPENSEARCH_HOST from Terraform output
#   VALKEY_HOST/PORT from Terraform output
# (Optional) set LLM provider credentials (OCI, OpenAI, Bedrock, or Ollama)
```

2) Install deps and run the app:

```bash
uv sync --extra pdf --extra office --extra vision --extra audio
uv run searchapp
```

Open http://0.0.0.0:8000


## Configuration

Key environment variables (see .env.example for full list):

- Database (system-of-record):
  - DATABASE_URL or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD, DB_SSLMODE
- Retrieval backend (default OpenSearch):
  - SEARCH_BACKEND=opensearch | pgvector
  - DB_STORE_EMBEDDINGS=false (recommended when serving from OpenSearch)
- OpenSearch:
  - OPENSEARCH_HOST, OPENSEARCH_INDEX (default spacesai_chunks)
  - OPENSEARCH_USER/OPENSEARCH_PASSWORD (if required)
  - OPENSEARCH_TIMEOUT/RETRIES/VERIFY_CERTS
  - OPENSEARCH_DUAL_WRITE=true
- Valkey:
  - VALKEY_HOST, VALKEY_PORT, VALKEY_PASSWORD (if any), VALKEY_DB, VALKEY_TLS, CACHE_TTL_SECONDS
- Storage backends:
  - STORAGE_BACKEND=local|oci|both
  - OCI_OS_BUCKET_NAME (required when using oci/both)
- LLM Providers:
  - LLM_PROVIDER=oci|openai|bedrock|ollama
  - OCI: standard OCI Generative AI envs
  - OpenAI: OPENAI_API_KEY and OPENAI_MODEL
  - Bedrock: AWS_REGION and AWS_BEDROCK_MODEL_ID (see AWS config below)
  - Ollama: OLLAMA_HOST (default http://localhost:11434), OLLAMA_MODEL


### AWS Bedrock configuration (if using ‘bedrock’)

1) Install AWS CLI and configure credentials and region:
```bash
aws configure
# Set AWS Access Key, Secret Key, default region (e.g. us-east-1), and default output
```

2) Ensure Bedrock access and model availability in your AWS account/region.

3) Set .env:
```env
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
AWS_BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
```

### Ollama configuration (if using ‘ollama’)

1) Install and run Ollama locally: https://ollama.com
2) Pull a model (e.g., llama3.2):
```bash
ollama pull llama3.2:latest
```
3) Set .env:
```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest
```


## Deployment options

- Bare VM (no containers)
  - Use the Compute VM cloud-init (or run bootstrap-infra.sh) to install system packages
  - Ensure PostgreSQL and OpenSearch/Valkey endpoints are reachable
  - Install deps and run:
    ```bash
    uv sync --extra pdf --extra office --extra vision --extra audio
    uv run searchapp
    ```

- Docker
  - Build and start:
    ```bash
    cd ..
    ./search-app/build-app.sh
    docker compose up -d
    ```
  - Stop:
    ```bash
    docker compose down
    ```

- Kubernetes
  - Push the image `spacesai:latest` to your registry and update deployment.yaml
  - Apply manifests:
    ```bash
    kubectl apply -f search-app/k8s/configmap.yaml
    kubectl apply -f search-app/k8s/deployment.yaml
    kubectl apply -f search-app/k8s/service.yaml
    ```
  - Access the service via ClusterIP or expose with Ingress/NodePort as needed

## Running locally


- Install deps and run:
```bash
uv sync --extra pdf --extra office --extra vision --extra audio
uv run searchapp
```
- UI: http://0.0.0.0:8000
- The settings gear in the UI includes provider selection for RAG (Default/OCI/OpenAI/Bedrock/Ollama).


## API Overview

Authentication for most endpoints is via session cookies acquired by /api/register or /api/login (Basic Auth fallback is present for legacy tools).

- Auth & Spaces:
  - POST /api/register {email,password}
  - POST /api/login {email,password}
  - POST /api/logout
  - GET  /api/me
  - GET  /api/spaces
  - POST /api/spaces {name}
  - POST /api/spaces/default {space_id}

- Upload & Retrieval:
  - POST /api/upload (multipart files[]; optional form space_id)
  - POST /api/search { query, mode: semantic|fulltext|hybrid|rag, top_k, space_id?, llm_provider? }
  - GET  /api/doc-summary?doc_id=
  - GET  /api/chunks-preview?doc_id=&limit=

- LLM & Providers:
  - GET  /api/providers
  - POST /api/chat { question, context?, provider? }
  - POST /api/llm-test { provider?, question, context }
  - GET/POST /api/llm-debug (OCI diagnostics)

- Admin (user-scoped):
  - GET    /api/admin/documents?space_id?&limit?&offset?
  - DELETE /api/admin/documents/{doc_id}
  - POST   /api/admin/reindex { doc_id | space_id | all: true }


## End-to-End Flow

1) Register/login → default space created
2) Upload files → ingestion extracts/chunks/embeds; dual-write to OpenSearch; file stored under <email>/YYYY/MM/DD/HHMMSS/<filename> (local and/or OCI)
3) Search → KNN/BM25 via OpenSearch with Valkey caching; RAG optionally with selected provider
4) Admin → list/delete docs; reindex scope (doc/space/all)


## Integration Tests (pytest)

A smoke test file is provided at `tests/test_api_smoke.py`. It includes:
- Health and providers listing (no DB required)
- Register/login/me (skipped when DB config is missing)
- LLM test call (unified LLM)

You can expand with upload → search → reindex flows by adding tests that:
- create a user, upload a small text file, call /api/search for hits, call /api/admin/reindex then search again.
These tests should be decorated with skip conditions unless DB and OpenSearch are reachable and configured.

Run tests:
```bash
pytest -q
```


## Troubleshooting

- Ensure DB connectivity and SSL settings are correct.
- For OpenSearch: verify OPENSEARCH_HOST and index mapping (vector dimensions must match EMBEDDING_DIM).
- For Valkey: check host/port/tls; caching is best-effort and does not block searches.
- For Bedrock: confirm AWS credentials/region and model access.
- For Ollama: ensure the local server is running and model is available.


## License
Apache-2.0
