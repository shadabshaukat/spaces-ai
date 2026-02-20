# SpacesAI – 4‑Stage Implementation Plan (UI, Search, RAG/DR, Security, Caching, APIs, Auditing)

This roadmap sequences all requested and recommended features into four testable stages. Each stage is self‑contained, deployable, and includes DB migrations (PostgreSQL), env flags, UI/UX work, backend changes, tests, and acceptance criteria. Observability logs/metrics are normalized into PostgreSQL tables (plus user_activity for event trails). Audio/Video ingestion is explicitly removed from the app.

Guiding principles
- Keep deployments incremental and reversible; avoid index mapping breaking changes unless absolutely needed
- Record all critical observability in Postgres for reliable analytics; minimize cardinality explosion
- Preserve existing UI simplicity; add controls as progressive disclosure (settings/gear or DR modal)
- Cache is best‑effort; correctness is ensured via revision invalidation on writes
- Secure defaults for production

Prerequisites
- OpenSearch reachable and configured (or pgvector fallback path remains intact)
- Valkey reachable for cache (optional but recommended)
- .env updated per stage’s new flags

------------------------------------------------------------
Stage 1 — Foundations: Security, Postgres Observability, Cache Invalidation, Baseline Retrieval
Scope (complete, testable): Hardening + instrumentation + correctness improvements without UX overhaul.

1) Security hardening and AV removal
- Env (config.py defaults for production):
  - ALLOW_CORS=false (or specific CORS_ORIGINS)
  - COOKIE_SECURE=true (behind TLS), COOKIE_SAMESITE=Strict
  - ALLOW_REGISTRATION=false (toggle for prod)
  - BASIC_AUTH_ENABLED=false (new) to disable fallback by default
  - RATE_LIMIT_ENABLED=true (new), RATE_LIMIT_RPM=120 (per IP+user)
  - CSRF_REQUIRED=true (new) for session‑cookie POSTs from browser
- Code changes:
  - auth.py: respect BASIC_AUTH_ENABLED; keep Basic only when explicitly enabled
  - main.py: wire slowapi/redis for rate limiting (keys ip+user); add CSRF middleware/token check (double submit with header)
  - templates/index.html: include CSRF token header on POSTs
  - Remove Audio/Video ingestion/search:
    - main.py ALLOWED_EXTS: drop audio/video extensions
    - text_utils.read_text_from_file: remove audio/video branches; raise for such types
    - README/docs: reflect supported types (documents + images with OCR)

2) Postgres observability (logs/metrics)
- Tables (DDL):
  - request_log(id bigserial pk, ts timestamptz default now(), user_id bigint null, path text, method text, status smallint, latency_ms int, space_id bigint null, ip inet null, user_agent text, cache_hit boolean, error text null)
  - search_log(id pk, ts, user_id, space_id, query text, mode text, top_k int, backend text, latency_ms int, cached boolean, result_count int, top_doc_ids bigint[], used_llm boolean)
  - llm_log(id pk, ts, user_id, space_id, provider text, model text, prompt_chars int, answer_chars int, prompt_hash text, success boolean, latency_ms int, token_prompt int null, token_completion int null, error text null)
  - dr_log(id pk, ts, user_id, space_id, conversation_id text, message_chars int, topic_lock boolean, subqueries text[], answer_chars int, prompt_hash text, success boolean, latency_ms int)
  - Indices: btree on (ts desc), (user_id, ts desc), (space_id, ts desc) as appropriate
- Code changes:
  - main.py: middleware to time every request and write request_log; add try/finally blocks in /api/search, /api/chat, /api/deep-research/* to write search_log/llm_log/dr_log rows
  - Hash any sensitive prompt/answer payloads (SHA256) and also store truncated samples (e.g., first 256 chars) only if AUDIT_MASK_PII=false
- Env:
  - AUDIT_ENABLE=true (default true), AUDIT_MASK_PII=true (default true), AUDIT_RETAIN_DAYS=90
- Retention:
  - Simple daily cleanup on startup (or cron): delete from *_log where ts < now() - interval 'AUDIT_RETAIN_DAYS days'

3) Cache correctness – revisioned keys
- Design: per‑user/per‑space revision key in Valkey: rev:u:{uid}:s:{sid}
- search keys become: v1:rev:{rev}:sem|fts|hyb:{uid}:{sid}:{topk}:{normalized_query}
- On ingest/delete/reindex, INCR the rev key
- Files:
  - search.py: include revision prefix; use unified helper to build cache keys
  - store.py (ingest_file_path) and main.py delete/reindex endpoints: bump rev
  - valkey_cache.py: no change except optional compression flag in Stage 2

4) Retrieval baseline improvements
- OpenSearch adapter: BM25 change to multi_match with field boosts
  - text^1.0, title^2.5, file_name^2.0; add metadata.title when available
  - Add optional filters: file_type(s), created_at range (API optional now; UI later)
- Hybrid: doc‑level dedup/aggregation
  - After initial sem/fts lists, group by document_id; score=best chunk or sum of top3 RRF scores; expand top docs with best chunk
- Optional MMR (env‑gated, default off)
  - HYBRID_MMR_ENABLE=false, HYBRID_MMR_LAMBDA=0.5, HYBRID_MMR_K=top_k

5) Tests and acceptance
- Unit: key building with revision, OS BM25 query body formation, grouping/dedup logic
- Integration (skipped without OS/DB): upload small files → search hybrid returns grouped hits; revision invalidates cache on new upload
- Acceptance criteria:
  - Security flags enforce stricter defaults; AV types rejected
  - request_log/search_log populated; cache invalidates immediately on ingest/delete
  - Hybrid yields grouped per‑doc results with boosted titles

------------------------------------------------------------
Stage 2 — Deep Research Quality: Topic Lock, Entity/Keyword Re‑ranker, Runtime DR Config
Scope (complete, testable): DR controls + reranking with UI toggles and audits.

1) DR topic control & re‑ranker
- Env (config.py):
  - DR_RERANK_ENABLE=true (default true)
  - DR_TOPIC_LOCK_DEFAULT=false
  - DR_TOPIC_LOCK_PENALTY=0.6 (0..1)
  - DR_RERANK_MAX_TERMS=20, DR_RERANK_METHOD=keywords (future: spacy)
- Backend (deep_research.py):
  - Extract topic signature from last N messages + current message using fast keyword scorer (tf‑idf‑like terms, noun‑phrase heuristic)
  - After hybrid_search(sq, top_k=12), compute overlap score; if topic_lock, apply strong penalty to zero‑overlap chunks; rerank and trim
  - Accumulate contexts from reranked hits
  - Log to dr_log: topic_lock flag, subqueries, latency
- API (main.py):
  - /api/deep-research/ask accepts topic_lock (optional), else default from env; pass to DR
- UI (index.html):
  - DR modal header: add “Topic lock” toggle (persist per‑space via localStorage) and display hint when active

Note: DR UI now supports ordered list numbering, code fence rendering, and follow-up chips; ensure any new layouts preserve these behaviors.

2) Runtime DR config endpoint (optional)
- GET/POST /api/dr-config to inspect/set DR_TOPIC_LOCK_DEFAULT and DR_RERANK_ENABLE (process‑local overrides similar to search-config)

3) Tests and acceptance
- Unit: keyword extraction stability, re‑ranking penalties, serialization of DR state
- Integration: DR conversation with/without topic lock shows measurable difference in references; dr_log populated
- Acceptance criteria:
  - Topic lock toggle round‑trip works; reranker affects references; logs show topic_lock=true/false

------------------------------------------------------------
Stage 3 — Image Understanding + Extractor Upgrades
Scope (complete, testable): Better ingestion for images and documents; optional CPU‑friendly models; no AV.

1) Image captioning add‑on (optional)
- Env (config.py):
  - IMAGE_CAPTIONING=false (default)
  - IMAGE_CAPTION_MODEL=Salesforce/blip-image-captioning-base
  - IMAGE_CAPTION_MAX_LEN=64
- New module app/vision.py:
  - Lazy‑load transformers pipeline (image‑to‑text) to MODEL_CACHE_DIR; CPU‑friendly
  - caption_image(path) -> {caption, labels?}
- text_utils.extract_text_from_image:
  - When enabled, prepend: “Image description: …; Objects: …” to OCR text before chunking
- pyproject extras: [vision]
- Metrics: record caption latency, enabled flag into request_log/search_log where relevant

2) Incremental extractor improvements
- HTML: optional readability pass; strip aside/figure/noscript/ads; retain headings/emphasis
  - Env: EXTRACT_HTML_READABILITY=false (default)
- DOCX/PPTX: capture alt‑text when present; extract table headers as separate lines
  - Env: EXTRACT_DOCX_ALT_TEXT=true, EXTRACT_TABLE_HEADERS=true
- XLSX/CSV: optional header handling and chunk by logical blocks (blank row separators)
  - Env: EXTRACT_TABLE_CHUNKING=true
- JSON: key‑path breadcrumbs (e.g., user.profile.name: John)
  - Env: EXTRACT_JSON_BREADCRUMBS=true
- text_utils.py: implement gated behaviors; update tests

3) Tests and acceptance
- Unit: image caption prepend; JSON breadcrumb formatter; HTML readability branch
- Integration: ingest sample docs/images → search returns improved snippets; no AV accepted
- Acceptance criteria:
  - When enabled, images show captions in results; improved HTML/Office/JSON parsing as per flags

------------------------------------------------------------
Stage 4 — UX Polish, Streaming, Advanced APIs, Admin/Retention
Scope (complete, testable): End‑user polish, streaming answers, filters, admin/audit tools, and operational docs.

1) Streaming answers (SSE)
- Endpoints: GET /api/search/stream (for rag), GET /api/deep-research/ask/stream
- UI: stream into answer panel with a typing animation; graceful fallback to non‑streaming
- Metrics: per‑chunk timing and completion summary into llm_log

2) Advanced search filters & config
- API: extend /api/search with filters {file_types:[], date_from, date_to}; reflect in OS bool filter and FTS SQL
- UI: filter chip bar (file types, date range)
- Runtime config: add search backend tuning help text; preserve existing endpoints

3) Admin endpoints and data management
- /api/admin/cache/invalidate {space_id?}: bump revision key
- /api/admin/audit/export?from=&to=&type=&format=ndjson|csv
- Retention job: configurable; document in README
- SQL Views: analytics views for request/search/llm/dr logs (e.g., hourly latency, cache hit rate, provider usage)

4) Ops and docs
- README updates for new flags and features; example dashboards (SQL snippets)
- K8s manifests: resource limits (already exist); add probes for /api/health and /api/ready

5) Tests and acceptance
- Streaming e2e; filters correctness with OS + FTS backends; admin export formats
- Acceptance criteria:
  - Smooth streamed answers; filters work; admins can invalidate caches and export audits

------------------------------------------------------------
Database migrations (summary DDL)

CREATE TABLE IF NOT EXISTS request_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
  path TEXT NOT NULL,
  method TEXT NOT NULL,
  status SMALLINT NOT NULL,
  latency_ms INT NOT NULL,
  space_id BIGINT NULL REFERENCES spaces(id) ON DELETE SET NULL,
  ip INET NULL,
  user_agent TEXT NULL,
  cache_hit BOOLEAN,
  error TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_request_log_user_ts ON request_log(user_id, ts DESC);

CREATE TABLE IF NOT EXISTS search_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
  space_id BIGINT NULL REFERENCES spaces(id) ON DELETE SET NULL,
  query TEXT NOT NULL,
  mode TEXT NOT NULL,
  top_k INT NOT NULL,
  backend TEXT NOT NULL,
  latency_ms INT NOT NULL,
  cached BOOLEAN,
  result_count INT,
  top_doc_ids BIGINT[],
  used_llm BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_search_log_ts ON search_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_search_log_user_ts ON search_log(user_id, ts DESC);

CREATE TABLE IF NOT EXISTS llm_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
  space_id BIGINT NULL REFERENCES spaces(id) ON DELETE SET NULL,
  provider TEXT NOT NULL,
  model TEXT NULL,
  prompt_chars INT,
  answer_chars INT,
  prompt_hash TEXT,
  success BOOLEAN,
  latency_ms INT,
  token_prompt INT NULL,
  token_completion INT NULL,
  error TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_log_ts ON llm_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_log_user_ts ON llm_log(user_id, ts DESC);

CREATE TABLE IF NOT EXISTS dr_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
  space_id BIGINT NULL REFERENCES spaces(id) ON DELETE SET NULL,
  conversation_id TEXT NOT NULL,
  message_chars INT,
  topic_lock BOOLEAN,
  subqueries TEXT[],
  answer_chars INT,
  prompt_hash TEXT,
  success BOOLEAN,
  latency_ms INT
);
CREATE INDEX IF NOT EXISTS idx_dr_log_ts ON dr_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_dr_log_user_ts ON dr_log(user_id, ts DESC);

(Keep existing user_activity for event trails: upload/search/delete_doc.)

------------------------------------------------------------
Environment variables added by stage
- Stage 1: BASIC_AUTH_ENABLED, RATE_LIMIT_ENABLED, RATE_LIMIT_RPM, CSRF_REQUIRED, AUDIT_* (enable/mask/retention), HYBRID_MMR_* (optional), ALLOW_CORS tightened, COOKIE_SECURE/COOKIE_SAMESITE stricter; remove AV support
- Stage 2: DR_RERANK_ENABLE, DR_TOPIC_LOCK_DEFAULT, DR_TOPIC_LOCK_PENALTY, DR_RERANK_MAX_TERMS, DR_RERANK_METHOD
- Stage 3: IMAGE_CAPTIONING, IMAGE_CAPTION_MODEL, IMAGE_CAPTION_MAX_LEN, EXTRACT_HTML_READABILITY, EXTRACT_DOCX_ALT_TEXT, EXTRACT_TABLE_HEADERS, EXTRACT_TABLE_CHUNKING, EXTRACT_JSON_BREADCRUMBS
- Stage 4: none mandatory; add STREAMING_ENABLE if desired

------------------------------------------------------------
Release and rollout notes
- Stage 1 ships first; ensure TLS and cookie Secure=true. Apply DB migrations. No OS index change required.
- Stage 2 modifies only DR logic, guarded by env flags. Safe to toggle.
- Stage 3 adds optional model deps under [vision] extra; guard with flags. No mapping change.
- Stage 4 adds new GET SSE endpoints and optional admin tools; backward‑compatible.

------------------------------------------------------------
Acceptance test matrix (high level)
- S1: Security headers, no AV uploads, logs populated, cache invalidates immediately
- S2: DR topic lock visible in UI; affects ranking; dr_log rows present
- S3: With flags on, images get captions; HTML/Office/JSON parsing improvements observable in search results
- S4: Streaming answers render progressively; filters narrow results; admin cache invalidate and audit export function

End of plan.