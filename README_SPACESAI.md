# SpacesAI Stack and Change Log

This document is the single source of truth for the SpacesAI product in this repository. It explains the complete architecture, technology stack, polyglot persistence layout, all changes made during the refactor from the original Enterprise Search App, configuration, deployment notes, and future work. Keep this file open while developing; if context is lost in future sessions, this file allows you to resume quickly.


## 1) What is SpacesAI?

SpacesAI is a multi-tenant, production-oriented, Google NotebookLM-like SaaS that lets users upload their own files and perform Retrieval-Augmented Generation (RAG) across multimodal content (PDF, DOCX, PPTX, XLSX, images via OCR, audio/video via transcription). Users have private “Spaces” (knowledge bases) where their data is isolated. The system tracks user activity (uploads, queries) for product analytics and operates on Oracle Cloud Infrastructure (OCI).


## 2) Architecture Overview (Polyglot Persistence)

- Web/API layer: FastAPI
- UI: Minimal Jinja-based, responsive single-page with login/register, space selection, upload with progress, and RAG search
- Authentication: Session cookie (HMAC-signed), Basic Auth fallback for API tools
- Persistence (polyglot):
  - PostgreSQL (OCI PostgreSQL): system-of-record for tenants (users, spaces), document metadata, activity; optional chunk embeddings (pgvector) when SEARCH_BACKEND=pgvector
  - OpenSearch (OCI OpenSearch): serving backend for retrieval (vector KNN + BM25/FTS) at scale; stores chunk text + embedding vectors and metadata
  - Object Storage (OCI): binary file storage, per-user email prefix with YYYY/MM/DD folders
  - OCI Cache (Valkey/Redis-compatible): caching of search results and other hot data
- Embeddings: Sentence-Transformers (default MiniLM 384 dims) with batched encoding, HF cache respected
- LLMs: OCI Generative AI or OpenAI (optional) for RAG response synthesis


## 3) Data Model and Isolation

- users(id, email, password_hash, created_at, last_login_at)
- spaces(id, user_id, name, is_default, created_at)
- documents(id, user_id, space_id, source_path, source_type, title, metadata, created_at)
- chunks(id, document_id, chunk_index, content, content_tsv GENERATED, content_chars, embedding vector(dim) NULL, embedding_model, created_at)
- user_activity(id, user_id, activity_type, details JSONB, created_at)

OpenSearch index (default: spacesai_chunks) mapping fields:
- doc_id (long), chunk_index (int), text (text), file_name (keyword), source_path (keyword), file_type (keyword), user_id (long), space_id (long), created_at (date), vector (knn_vector with HNSW/cosine)

Isolation: all queries/ingestion include user_id (+ optional space_id) so users only see their own data.


## 4) Storage layout in OCI Object Storage

- Objects are written under: <email>/YYYY/MM/DD/HHMMSS/<filename>
- Email is sanitized for the path ("@" -> "_at_", alnum/._- only)
- Both local disk and OCI writes are supported; streaming uploads avoid loading full files in memory


## 5) Core Flows

- Register/Login: Creates user row and default space; issues session cookie
- Upload: Streams each file, stores to local/OCI; extracts text (PDF/HTML/TXT/DOCX/PPTX/XLSX/CSV/MD/JSON/Images OCR/Audio+Video transcription), chunks and embeds, inserts metadata into Postgres, and dual-writes chunks+vectors to OpenSearch (best-effort). Activity logged.
- Search: Per-user/per-space hybrid retrieval (OpenSearch KNN + BM25 via RRF), wrapped with recency-aware scoring when enabled; caches results in Valkey; optional LLM synthesis; returns hits + references with OCI object links when available. Activity logged.


## 6) Tech Stack (code locations)

- search-app/app/main.py — FastAPI app, routes, auth endpoints, spaces mgmt, upload & search APIs, activity logging
- search-app/app/config.py — Settings (ENV driven), includes OpenSearch/Valkey/OCI
- search-app/app/db.py — psycopg pool + idempotent schema creation (extensions: vector, pgcrypto, citext)
- search-app/app/store.py — Upload/ingest; dual-write to OpenSearch
- search-app/app/search.py — Retrieval: semantic (KNN), fulltext (BM25/FTS), hybrid; caches via Valkey
- search-app/app/opensearch_adapter.py — Minimal adapter for OS index ensure, bulk index, and search APIs
- search-app/app/valkey_cache.py — Thin Redis/Valkey client with get/set JSON + TTL
- search-app/app/text_utils.py — Extractors: PDF, HTML, TXT, DOCX, PPTX (python-pptx), XLSX (openpyxl), CSV, MD, JSON, Images (pillow+pytesseract), Audio/Video (ffmpeg + whisper)
- search-app/app/templates/index.html + static/style.css — Rebranded SPACE-AI UI with login/register & spaces


## 7) Configuration (Environment)

Edit search-app/.env.example and copy to .env. Key fields:

- App/Server: HOST, PORT, WORKERS, APP_NAME, SECRET_KEY, SESSION_* vars
- Database (system-of-record): DATABASE_URL or DB_HOST/NAME/USER/PASSWORD; DB_SSLMODE
- Storage: STORAGE_BACKEND=local|oci|both; OCI_OS_BUCKET_NAME; MAX_UPLOAD_SIZE_MB; DELETE_UPLOADED_FILES
- Chunking: CHUNK_SIZE, CHUNK_OVERLAP
- Embeddings: EMBEDDING_MODEL, EMBEDDING_DIM, EMBEDDING_BATCH
- Retrieval backend:
  - SEARCH_BACKEND=opensearch | pgvector
  - DB_STORE_EMBEDDINGS=true|false (if pgvector path is used and you want to persist vectors in Postgres)
- OpenSearch (serving): OPENSEARCH_HOST, OPENSEARCH_INDEX, OPENSEARCH_USER/PASSWORD, OPENSEARCH_TIMEOUT/RETRIES/VERIFY_CERTS, OPENSEARCH_DUAL_WRITE
- Valkey (cache): VALKEY_HOST, VALKEY_PORT, VALKEY_PASSWORD, VALKEY_DB, VALKEY_TLS, CACHE_TTL_SECONDS
- Deep Research follow-ups:
  - DEEP_RESEARCH_FOLLOWUP_AUTOSEND (default true) auto-sends follow-up chips when clicked; set false to insert text only
  - DEEP_RESEARCH_FOLLOWUP_RELEVANCE_MIN (0-1 float, default 0.08) filters follow-ups by similarity to the current question or recent conversation; increase for stricter filtering
- OCI GenAI (optional LLM): region, endpoint, compartment, model id, and auth (config file or API key envs)


## 8) Running Locally

1) Configure .env
2) Install deps and start server:

```
cd search-app
uv sync --extra pdf --extra office --extra vision --extra audio
uv run searchapp
```

Visit http://0.0.0.0:8000, register/login, create/select a space, upload and search.


## 9) OpenSearch & Valkey Integration Details

- Ingestion dual-write to OpenSearch:
  - Controlled by OPENSEARCH_DUAL_WRITE=true (default on) and SEARCH_BACKEND=opensearch
  - DB remains the system-of-record for tenants and documents; OpenSearch is the serving layer for retrieval
  - Errors during OS indexing are logged as warnings; ingestion proceeds
- Search paths:
  - semantic -> OpenSearch KNN (vector) with user/space filters; cache key: sem:{user}:{space}:{topk}:{query}
  - fulltext -> OpenSearch BM25 with user/space filters; cache key: fts:{...}
  - hybrid -> simple RRF across semantic + fulltext
- Recency weighting:
  - If DEEP_RESEARCH_RECENCY_BOOST is set, both semantic and fulltext queries are wrapped in a function_score with a gauss decay on created_at
  - This favors newer chunks without overriding relevance; adjust DEEP_RESEARCH_RECENCY_SCALE_DAYS to widen/narrow the time window
- Valkey cache:
  - redis-py used with small timeouts and TTL (default 300s)
  - Cache miss triggers backend search, then caches a compact JSON version of hits
- Index layout and creation:
  - The adapter ensures the index exists on startup with knn=true and HNSW configuration sized to EMBEDDING_DIM
  - Shards/replicas are configurable via env: OPENSEARCH_SHARDS (default 3), OPENSEARCH_REPLICAS (default 1)


## 10) Terraform (Infrastructure)

The existing `oci_postgres_tf_stack` provisions the VCN/subnets, NAT/IGW, NSGs, an OCI PostgreSQL DB System, optional Compute, and an Object Storage bucket for uploads.

New resources were added to the same module to provision OCI OpenSearch and OCI Cache (Valkey) into the same VCN:

- Variables (vars.tf):
  - enable_opensearch, opensearch_display_name, opensearch_version, opensearch_node_count, opensearch_ocpus, opensearch_memory_gbs, opensearch_storage_gbs
  - enable_cache, cache_display_name, cache_node_count, cache_memory_gbs

- Resources:
  - opensearch.tf — creates `oci_opensearch_opensearch_cluster.spacesai_os` and NSG ingress for 9200 (from within VCN)
  - cache.tf — creates `oci_cache_redis_cluster.spacesai_cache` and NSG ingress for 6379 (from within VCN)

- Outputs (outputs.tf):
  - opensearch_endpoint — HTTPS endpoint of the cluster (scaffolded attribute)
  - valkey_hostname, valkey_port — Cache connection details (scaffolded attributes)

- Networking: both services attach to `vcn1_psql_priv_subnet` by default (or `psql_subnet_ocid` when reusing an existing subnet). Update NSGs as needed for your deployment. All services remain private.

IMPORTANT: The exact resource type/attributes may vary with the OCI provider version. If your provider exposes different names/fields, replace the resource type names and attribute selectors accordingly. After `terraform apply`, map the outputs to the app `.env`:

```
OPENSEARCH_HOST=https://<opensearch_endpoint>
OPENSEARCH_INDEX=spacesai_chunks
VALKEY_HOST=<valkey_hostname>
VALKEY_PORT=<valkey_port>
```

Run:

```
cd oci_postgres_tf_stack
terraform init
terraform apply -var-file=example.tfvars
```

Then update `search-app/.env` with the outputs and run the app.


## 11) Security Considerations

- Session cookie is HttpOnly, SameSite=Lax; set Secure attribute behind TLS
- Restrict CORS in production
- Store secrets in OCI Vault/Secrets; do not commit real credentials
- DB and service subnets should be private; use NAT for egress
- Front the app with a TLS-terminating proxy/WAF


## 12) Change Log (this refactor)

- 2026-02-21: Documented new Deep Research follow-up settings:
  - DEEP_RESEARCH_FOLLOWUP_AUTOSEND (auto-send chips)
  - DEEP_RESEARCH_FOLLOWUP_RELEVANCE_MIN (relevance threshold with tuning guidance)
- Added multi-tenant auth and spaces: users, spaces, user_activity tables; citext extension
- Implemented session cookie auth; Login/Register/Logout; /api/me, /api/spaces, /api/spaces/default
- Rebranded UI to SPACE-AI and added login/register + space selection/creation
- Enforced per-user/space scoping on upload/search/doc APIs
- Implemented streaming uploads; per-user email path in Object Storage
- Extended text extraction: PPTX, XLSX, Images (OCR), Audio/Video (transcription)
- Integrated OpenSearch (adapter, dual-write on ingest); integrated Valkey cache for retrieval
- Added OpenSearch recency weighting (created_at mapping, decay scoring) and reindex support for backfilling created_at
- SEARCH_BACKEND switch and DB_STORE_EMBEDDINGS flag; OpenSearch is default serving layer
- Added unified LLM module with providers: OCI, OpenAI, AWS Bedrock, and Ollama; new /api/chat and /api/llm-test allow provider override
- search-app/.env.example updated with OpenSearch/Valkey/Bedrock/Ollama settings
- pyproject updated to include opensearch-py, redis, boto3, requests
- Terraform: added opensearch.tf, cache.tf, and outputs for endpoints
- Terraform: added Cloud-init support for Compute (enable_cloud_init, compute_app_port, repo_url, cloud_init_user_data). Default script installs curl, git, unzip, firewalld, oraclelinux-developer-release-el10, python3-oci-cli, postgresql16, tesseract, ffmpeg, uv, AWS CLI v2, Docker & Compose; opens port 8000; clones repo. Notes added for first-boot behavior.
- search-app: ensure-index now configures number_of_shards/replicas via env OPENSEARCH_SHARDS/OPENSEARCH_REPLICAS (defaults 3/1)
- Added scripts: search-app/bootstrap-infra.sh (sudo-only bootstrap), search-app/build-app.sh, search-app/start-app.sh, search-app/stop-app.sh
- Added Dockerfile for app and root docker-compose.yml (binds 0.0.0.0, mounts storage, maps port)
- Added Kubernetes manifests: search-app/k8s (Deployment/Service/ConfigMap) with resource requests/limits, probes, and env integration
- Documentation: Root README.md and search-app/README.md updated with cloud-init packages/commands and deployment strategies for Bare VM, Docker, and Kubernetes
- Deep Research UI formatting fixes: ordered lists render with proper numbering, code fences render as blocks, and follow-up questions appear as auto-send chips
- Added CLI helper (reindexcli) to reindex OpenSearch from Postgres for a user/space/doc


## 13) Roadmap / Next Steps

- Terraform: add `opensearch.tf` and `cache.tf` with confirmed OCI resource types, attach to `vcn1_psql_priv_subnet`, and create NSGs for 9200/6379
- Optional: Disable DB vector storage by default when serving from OpenSearch (insert chunks without vectors) and provide backfill tooling
- Add integration/contract tests for adapters and caching layer
- Admin endpoints for listing/deleting documents per space and reindex controls
- Ensure reindex CLI is run after enabling recency weighting so existing OpenSearch chunks have created_at
- Streaming /api/search responses and UI improvements for citations
- Optional: Add HorizontalPodAutoscaler and Ingress manifests for K8s
- Optional: systemd service unit for bare VM auto-start


## 14) How to Resume Work

- Review this README_SPACESAI.md for architecture and change list
- Export the necessary env vars or copy .env.example to .env and set values
- To develop locally: `uv sync --extra pdf --extra office --extra vision --extra audio && uv run searchapp`
- If you enable OpenSearch recency weighting, run `uv run reindexcli --email <user>` to backfill created_at for existing chunks
- To integrate Terraform: update variables and add opensearch.tf/cache.tf, then plan/apply


---
Maintainers: update this file with every material change to code, infrastructure, or configuration so future sessions can pick up seamlessly.
