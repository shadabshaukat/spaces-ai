# SpacesAI Application (FastAPI + OCI PostgreSQL + OpenSearch + Valkey)

SpacesAI is a multi-tenant, production-grade, NotebookLM-like application. Users create private Spaces, upload their own files, and run Retrieval-Augmented Generation (RAG) over multimodal content (PDF, DOCX, PPTX, XLSX, images via OCR, audio/video transcription). The stack is polyglot:

- PostgreSQL (OCI) — system-of-record for users, spaces, documents, activity
- OpenSearch (OCI) — serving backend for retrieval (KNN vectors + BM25/FTS)
- Object Storage (OCI) — binary file storage (per-user email/date prefixes)
- Valkey (OCI Cache, Redis-compatible) — caching search results
- LLM providers: OCI Generative AI, OpenAI, AWS Bedrock, and local Ollama

This README covers application setup, configuration, endpoints, Deep Research workflows, the Postgres/OpenSearch MCP helper, and how to run locally. See the repo-level README and README_SPACESAI.md for infrastructure and architecture details.


## Features

- Multi-tenant auth with session cookies; private Spaces
- Upload → robust extractors (PDF/HTML/TXT/DOCX/PPTX/XLSX/CSV/MD/JSON/Images OCR/Audio+Video transcription + image embeddings/captions)
- Chunking + embeddings; dual-write to OpenSearch for retrieval
- Retrieval: semantic (KNN), fulltext (BM25), hybrid (RRF), **image search** (OpenCLIP + pgvector/OpenSearch)
- Deep Research mode with agentic planning, selective web lookups, confidence scoring, and rich reference metadata
- Recency-aware OpenSearch scoring via `created_at` decay
- RAG over the selected Space with unified, pluggable LLM providers
- Caching via Valkey to accelerate repeated queries (text + image namespaces)
- Admin APIs for listing/deleting documents and reindexing
 - Optional MCP server that exposes read-only SQL queries and OpenSearch diagnostics to editors like VS Code/Cursor


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
cd search-app
cp .env.example .env
# Edit DB connection and set:
#   SEARCH_BACKEND=opensearch
#   OPENSEARCH_HOST from Terraform output
#   VALKEY_HOST/PORT from Terraform output
# (Optional) set LLM provider credentials (OCI, OpenAI, Bedrock, or Ollama)
```

2) Install deps (including image/vision stack) and run the app:

```bash
uv sync --extra pdf --extra office --extra vision --extra audio --extra image
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
  - VALKEY_HOST, VALKEY_PORT, VALKEY_PASSWORD (if any), VALKEY_DB, VALKEY_TLS
  - CACHE_TTL_SECONDS (default 300s) controls semantic/BM25 result caching
  - LLM_CACHE_TTL_SECONDS (default 900s) controls cached RAG/LLM answers
  - CACHE_NAMESPACE + CACHE_SCHEMA_VERSION let you invalidate keys after schema changes
  - CACHE_FAILURE_THRESHOLD and CACHE_COOLDOWN_SECONDS enable circuit-breaking when OCI Cache is unhealthy
- Storage backends:
  - STORAGE_BACKEND=local|oci|both
  - OCI_OS_BUCKET_NAME (required when using oci/both)
- Deep Research:
  - DEEP_RESEARCH_TIMEOUT_SECONDS (default 120s) enforces end-to-end agent budget
  - DEEP_RESEARCH_WEB_SEARCH_PROVIDER=serpapi|bing|none (see `agentic_research.py` for adapters)
  - DEEP_RESEARCH_CONFIDENCE_BASELINE (0-1 float) lets you shift minimum displayed confidence
  - DEEP_RESEARCH_WEB_TIMEOUT_SECONDS caps web fetch attempts per sub-query
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


## Deployment

- Compute VM (recommended)
  - Use Compute VM cloud-init (or run bootstrap-infra.sh) to install system packages
  - Build deps:
    ```bash
    cd search-app
    ./build-app.sh
    ```
  - Run (foreground):
    ```bash
    ./run-app.sh --debug      # installs all extras, starts with verbose logs
    ```
  - Start (background):
    ```bash
    ./start-app.sh
    ```
  - Stop:
    ```bash
    ./stop-app.sh
    ```
  - Toggle debug logging:
    ```bash
    ./run-app.sh --no-debug   # disable verbose logs
    ./run-app.sh --debug      # (default) explicitly enable
    ./start-app.sh --no-debug # runs in background with DEBUG_LOGGING=false
    ```
    All launch scripts accept `--debug`/`--no-debug` and default to verbose logging. You can also export `DEBUG_LOGGING=false` before invoking any script to permanently reduce log noise in production.

## Running locally



- Install deps and run:
```bash
uv sync --extra pdf --extra office --extra vision --extra audio --extra image
uv run searchapp
```
- UI: http://0.0.0.0:8000
- The settings gear in the UI includes provider selection for RAG (Default/OCI/OpenAI/Bedrock/Ollama).


## Deep Research Workflow

Deep Research is an opt-in mode surfaced in the UI modal and `/api/deep-research` family of endpoints. The pipeline now:

1. Plans sub-questions using recent conversation context.
2. Retrieves local knowledge base hits with hybrid search.
3. Calls `SmartResearchAgent.decide_web_and_contexts()` to determine whether external web search is necessary. The agent uses the remaining timeout budget, hit density, and question type to decide.
4. Synthesizes an answer, optionally refining it with a second lightweight LLM pass.
5. Returns structured metadata:
   - `confidence` (0-1) derived from context quality + LLM self-report.
   - `web_attempted` boolean.
   - `elapsed_seconds` for the full pipeline.
   - `references` covering both local chunk IDs and web citations (title, URL, snippet).
   - `followup_questions` surfaced as clickable chips in the UI.

### Deep Research UI enhancements
- Ordered lists render with native numbering (fixes 1/1/1 bug).
- Code fences render as formatted `<pre><code>` blocks.
- Follow-up questions render as clickable chips that insert into the composer.

### Frontend indicators

The modal shows badges for confidence (color-coded), elapsed time, and whether web search was invoked. References render in two columns: local knowledge base entries and web citations. This keeps non-compliant content separated while still offering transparency to end users.

### API overview

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
  - POST /api/image-search { query?, tags?, top_k?, vector?, space_id? }
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

### Deep Research endpoints

- POST `/api/deep-research/start` → `{ conversation_id }`
- POST `/api/deep-research/ask { conversation_id, message, llm_provider?, force_web?, urls? }`
- GET  `/api/deep-research/conversations?space_id=`
- GET  `/api/deep-research/conversations/{conversation_id}`
- POST `/api/deep-research/conversations/{conversation_id}/title { title }`
- POST `/api/deep-research/notebook/{conversation_id} { title, content }`
- DELETE `/api/deep-research/notebook/{entry_id}`

Responses include `confidence`, `web_attempted`, `elapsed_seconds`, `references`, and `followup_questions` as described above.
- Optional MCP server that exposes read-only SQL queries and OpenSearch diagnostics to editors like VS Code/Cursor


## End-to-End Flow

1) Register/login → default space created
2) Upload files → ingestion extracts/chunks/embeds; dual-write to OpenSearch; file stored under <email>/YYYY/MM/DD/HHMMSS/<filename> (local and/or OCI)
3) Search → KNN/BM25 via OpenSearch with Valkey caching; RAG optionally with selected provider
4) Admin → list/delete docs; reindex scope (doc/space/all)

## CLI helpers

Reindex OpenSearch for an existing user (useful after `created_at` scoring changes):

```bash
uv run reindexcli --email you@example.com
uv run reindexcli --email you@example.com --space-id 123
uv run reindexcli --email you@example.com --doc-id 456 --refresh
```

Ingest local files into a user’s space (bulk upload):

```bash
uv run ingestcli --email you@example.com ./docs
```


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


## Database + OpenSearch MCP Server

Phase 4 introduces an auxiliary MCP (Model Context Protocol) server so that editors such as Cursor, WindSurf, or VS Code MCP clients can run read-only SQL queries and OpenSearch diagnostics without shelling into the app container.

- Location: `/Users/shadab/Documents/Cline/MCP/spacesai-db-os`
- Entry point: `python main.py`
- Configuration: `mcp.json` exposes environment variable names for Postgres (`DATABASE_URL` or discrete host/user/password) and OpenSearch (`OPENSEARCH_HOST`, `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD`).
- Tools:
  1. `spacesai_sql_select` — accepts a SQL string (must begin with `SELECT`) plus optional parameters, returning rows and column metadata. Enforces read-only access.
  2. `spacesai_opensearch_query` — accepts index name, query/type (`match`, `knn`, etc.), vector payloads, and returns JSON hits for debugging.

### Installation & usage

```bash
cd /Users/shadab/Documents/Cline/MCP/spacesai-db-os
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # already includes psycopg, opensearch-py, python-dotenv
python main.py
```

Then register the MCP server in your editor (Cursor example):

```jsonc
// cursor-mcp.json
{
  "spacesai-db-os": {
    "command": "/Users/shadab/Documents/Cline/MCP/spacesai-db-os/.venv/bin/python",
    "args": ["/Users/shadab/Documents/Cline/MCP/spacesai-db-os/main.py"],
    "env": {
      "DATABASE_URL": "postgresql://user:pass@host:5432/dbname",
      "OPENSEARCH_HOST": "https://search-domain:9200",
      "OPENSEARCH_USER": "admin",
      "OPENSEARCH_PASSWORD": "secret"
    }
  }
}
```

Once connected, the MCP client will list two tools named "SpacesAI SQL (SELECT only)" and "SpacesAI OpenSearch query". Calls return structured JSON, so you can ask your AI assistant to chain results into additional reasoning steps.

## Troubleshooting

- Ensure DB connectivity and SSL settings are correct.
- For OpenSearch: verify OPENSEARCH_HOST and index mapping (vector dimensions must match EMBEDDING_DIM). After mapping updates (e.g., `created_at`), run `reindexcli` or `/api/admin/reindex`.
- For Valkey: check host/port/tls; caching is best-effort and does not block searches.
- For Bedrock: confirm AWS credentials/region and model access.
- For Ollama: ensure the local server is running and model is available.


## License
Apache-2.0
