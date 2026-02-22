# Polyglot-AI-App: SpacesAI Deep Dive

This guide explains how SpacesAI works end‑to‑end for **agentic Deep Research**, **text search with RAG**, and **image search**. It also maps the polyglot data stack (OCI PostgreSQL + OpenSearch + Valkey + Object Storage) and how data flows between components.

---

## 1) Platform architecture at a glance

SpacesAI is a multi‑tenant, NotebookLM‑style platform for private data. It combines:

- **OCI PostgreSQL** for system‑of‑record storage (users, spaces, documents, chunks, metadata, DR sessions).
- **OCI OpenSearch** for high‑performance retrieval (BM25 + vector KNN) and recency‑aware ranking.
- **OCI Cache (Valkey)** for low‑latency caching of search and RAG results.
- **OCI Object Storage** for binary file persistence (uploads + thumbnails + optional presigned access).
- **LLM Providers** (OCI GenAI, OpenAI, Bedrock, Ollama) for RAG and agentic synthesis.

The design favors **local‑first retrieval** with optional web augmentation for Deep Research.

### Branding tone snapshot (OCI‑first, AI‑heavy)
SpacesAI is an **OCI‑powered polyglot AI platform** that blends **OCI OpenSearch, OCI PostgreSQL, and OCI Valkey** into a unified Retrieval‑Augmented Generation stack. It’s built for enterprise‑grade **agentic research**, **RAG search**, and **multimodal intelligence**—an open‑source‑friendly data engine with OCI scale.

---

## 2) Core data model

### PostgreSQL (system of record)
- `documents`: file metadata, source paths, storage metadata, timestamps.
- `chunks`: extracted text chunks + embeddings + FTS tsvector.
- `image_assets`: image thumbnails, tags, captions, OCR text, embeddings.
- DR sessions: conversation + notebook records.

### OpenSearch (serving layer)
- `spacesai_chunks`: BM25 + vector fields for chunk search.
- `spacesai_images`: image vectors + metadata for image search.

### Valkey (cache)
- Semantic/full‑text search result cache.
- RAG answer cache.
- Image search cache.
- DR state caching (per user + space namespace).

---

## 3) Upload & ingestion workflow

### What happens on upload
1. Client uploads file to `/api/upload`.
2. Server saves file locally and (optionally) mirrors to OCI Object Storage.
3. Text extraction + normalization runs per file type.
4. Content is chunked (default size/overlap) and embedded.
5. Postgres writes:
   - `documents` row
   - `chunks` rows (with embeddings if `DB_STORE_EMBEDDINGS=true`)
6. Optional dual‑write to OpenSearch for retrieval serving.
7. For images: captions, OCR, tags, and image embeddings are generated and stored.

### Upload → ingestion flow diagram
![Upload ingestion workflow](docs/diagrams/ingestion-flow.svg)

### Upload API payload (example)
```json
POST /api/upload
Content-Type: multipart/form-data

files: <binary>
space_id: 42
```

### Upload API response (example)
```json
200 OK
{
  "results": [
    {
      "document_id": 1284,
      "num_chunks": 22,
      "file_name": "privacy.pdf",
      "object_url": "https://objectstorage.../o/user/2026/02/23/privacy.pdf"
    }
  ]
}
```

---

## 4) Text search & RAG (Retrieval‑Augmented Generation)

### Retrieval modes
- **Semantic**: vector search (OpenSearch KNN or pgvector).
- **Full‑text**: BM25/TSVector (OpenSearch or PostgreSQL FTS).
- **Hybrid**: Reciprocal Rank Fusion (RRF) between semantic + full‑text.
- **RAG**: Hybrid retrieval + LLM synthesis.

### RAG pipeline (step‑by‑step)
1. **Embed query** (sentence‑transformer).
2. **Retrieve top‑k chunks** using chosen mode (semantic / full‑text / hybrid).
3. **Assemble context** from chunk text.
4. **LLM synthesis** (OCI GenAI / OpenAI / Bedrock / Ollama).
5. **Cache answer** in Valkey for fast repeat queries.

### Context Builder (how it works)
The **Context Builder** is the orchestration layer that transforms raw hits into an LLM‑ready prompt. It:

- **Deduplicates and ranks hits** (keeps the top‑k chunk order from retrieval, removes overlaps).
- **Normalizes chunk text** (removes duplicate whitespace, preserves paragraph boundaries).
- **Constructs a compact context block**: concatenates chunks with document labels, ready for LLM input.
- **Caches the final answer** by hashing the query + chunk IDs + context to guarantee repeatable results.

This keeps RAG deterministic, improves token efficiency, and ensures LLM responses are traceable to the same evidence set.

### RAG flow diagram
![RAG workflow](docs/diagrams/rag-flow.svg)

### RAG API payload (example)
```json
POST /api/search
{
  "query": "Summarize the privacy act changes",
  "mode": "rag",
  "top_k": 8,
  "space_id": 42,
  "llm_provider": "oci"
}
```

### RAG API response (example)
```json
200 OK
{
  "answer": "Here is a concise summary of the changes...",
  "used_llm": true,
  "hits": [
    {"chunk_id": 1284000000, "document_id": 1284, "chunk_index": 0, "content": "...", "distance": 0.12}
  ],
  "references": [
    {"doc_id": 1284, "file_name": "privacy.pdf", "file_type": "pdf", "chunk_id": 1284000000}
  ]
}
```

---

## 5) Agentic Deep Research workflow

Deep Research is an **agentic multi‑step pipeline** that plans sub‑questions, retrieves local evidence, selectively calls web search, and synthesizes a final answer with confidence metadata.

### Agentic pipeline (current implementation)
1. **Plan sub‑questions** from user query + recent context.
2. **Local hybrid retrieval** for each sub‑question.
3. **Coverage heuristic** (hits, doc diversity, semantic quality).
4. **Optional query rewrite** if evidence is weak.
5. **Web search fallback** if still weak (DuckDuckGo HTML scraping).
6. **Missing‑concept analysis** and targeted re‑retrieval loop.
7. **Grouped context synthesis** (local / URL / web / missing‑concepts).
8. **Return metadata**: confidence, web_attempted, elapsed seconds, references, follow‑up prompts.

### Deep Research workflow internals (expanded)
Deep Research is implemented as an **agentic loop** that balances local evidence with optional web retrieval:

1. **Planner** creates 2–4 sub‑questions to cover distinct angles.
2. **Local retrieval** runs hybrid search per sub‑question.
3. **Coverage scoring** checks:
   - Total hit count
   - Unique document count
   - Best semantic distance (quality proxy)
4. **Rewriting**: if weak, an LLM rewrites the query into a concise search phrase and retries.
5. **Web search gate**: only triggers if local coverage is still weak or if `force_web` is enabled.
6. **Missing‑concept loop**: LLM identifies gaps and re‑retrieves evidence for those gaps (configurable loops).
7. **Grouped context assembly**: local + URL + web + missing‑concept blocks are passed to the LLM.
8. **Synthesis**: LLM generates the final answer + confidence + follow‑ups.

This ensures **local‑first answers** while still offering agentic web augmentation when local context is insufficient.

### Deep Research flow diagram
![Deep Research workflow](docs/diagrams/deep-research-flow.svg)

### Deep Research API payloads (examples)
```json
POST /api/deep-research/start
{
  "space_id": 42
}
```

```json
200 OK
{
  "conversation_id": "dr_abc123"
}
```

```json
POST /api/deep-research/ask
{
  "conversation_id": "dr_abc123",
  "message": "Compare the AU Privacy Act and GDPR changes.",
  "space_id": 42,
  "llm_provider": "oci",
  "force_web": false
}
```

```json
200 OK
{
  "answer": "Both frameworks emphasize ...",
  "confidence": 0.72,
  "web_attempted": false,
  "elapsed_seconds": 18.4,
  "references": [
    {"source": "local", "document_id": 1284, "chunk_index": 3, "title": "privacy.pdf"}
  ],
  "followup_questions": ["Which provisions apply to cross-border transfers?"]
}
```

---

## 6) Image search workflow

SpacesAI supports image similarity using OpenCLIP embeddings with optional text and tag filters.

### Image ingestion
1. Upload image → stored locally + optional OCI Object Storage.
2. Generate thumbnail.
3. Create tags (orientation, filename tokens, dominant color, caption tokens, OCR tokens).
4. Generate caption (LLava‑style) and OCR text.
5. Embed image (OpenCLIP) and store in `image_assets`.
6. Dual‑write to OpenSearch image index.

### Image search query flow
1. User enters text query / tags / reference image.
2. If text or ref image, OpenCLIP creates query vector.
3. Backend searches:
   - **OpenSearch** for vector KNN + text rank (default)
   - **Postgres** fallback (vector + caption/OCR full‑text)
4. Results merge vector similarity and text rank weights.
5. UI renders thumbnails, tags, caption, and “Open document”.

### Image search diagram
![Image search workflow](docs/diagrams/image-search-flow.svg)

### Image search API payload (example)
```json
POST /api/image-search
{
  "query": "office building interior",
  "tags": ["architecture", "lobby"],
  "top_k": 12,
  "space_id": 42
}
```

### Image search API response (example)
```json
200 OK
{
  "count": 12,
  "results": [
    {
      "image_id": 77,
      "doc_id": 1284,
      "thumbnail_url": "/api/image-assets/77/thumbnail",
      "file_path": "uploads/user/2026/02/23/lobby.jpg",
      "caption": "Lobby interior with glass walls",
      "tags": ["lobby", "architecture", "blue"]
    }
  ]
}
```

---

## Authentication notes (API access)

SpacesAI supports **session cookies** after login and a **Basic Auth fallback** for legacy tooling.

### Login flow (session cookie)
```json
POST /api/login
{
  "email": "you@example.com",
  "password": "strong-password"
}
```

Response includes a session cookie (HTTP‑only). Subsequent requests should include that cookie automatically in the browser.

### Basic Auth (legacy tools)
For CLI or scripts, include a Basic Auth header:

```
Authorization: Basic base64(username:password)
```

Example curl:
```bash
curl -u admin:letmein http://localhost:8000/api/health
```

---

## Spaces & Admin endpoint examples

### Create a space
```json
POST /api/spaces
{
  "name": "Compliance Research"
}
```

```json
200 OK
{
  "space": {
    "id": 42,
    "name": "Compliance Research",
    "is_default": false
  }
}
```

### Set default space
```json
POST /api/spaces/default
{
  "space_id": 42
}
```

```json
200 OK
{
  "ok": true
}
```

### List documents (admin)
```json
GET /api/admin/documents?space_id=42&limit=25&offset=0
```

```json
200 OK
{
  "total": 128,
  "documents": [
    {"id": 1284, "title": "privacy.pdf", "created_at": "2026-02-23T04:10:00Z"}
  ]
}
```

### Delete a document
```json
DELETE /api/admin/documents/1284
```

```json
200 OK
{
  "ok": true,
  "deleted_id": 1284
}
```

### Reindex OpenSearch (space scope)
```json
POST /api/admin/reindex
{
  "space_id": 42
}
```

```json
200 OK
{
  "ok": true,
  "reindexed": 128
}
```

---

## 7) Polyglot stack: Postgres + OpenSearch + Valkey

SpacesAI deliberately uses different engines for what they do best:

- **OCI PostgreSQL** → authoritative record of users, documents, chunks, DR sessions.
- **OCI OpenSearch** → ultra‑fast retrieval (BM25 + vector KNN, recency decay).
- **OCI Valkey** → caching repeated searches and RAG answers for sub‑second responsiveness.

### Stack interaction diagram
![Polyglot stack interaction](docs/diagrams/polyglot-stack-flow.svg)

---

## 8) How chunks and embeddings move between components

1. **Extraction** produces plain text.
2. **Chunker** breaks text into overlapping blocks.
3. **Embedding model** produces vector per chunk.
4. **Postgres storage** saves chunk text + embedding.
5. **OpenSearch indexing** stores text + vector + metadata.
6. **Valkey caching** stores retrieval + RAG answers by query hash.

This keeps Postgres authoritative, OpenSearch fast, and Valkey responsive.

---

## 9) OCI‑friendly, AI‑heavy platform title ideas

Use these as session titles, talk tracks, or blog headlines. They are intentionally OCI‑centric, AI‑heavy, and tuned for search visibility.

1. **“OCI Polyglot AI Stack: Postgres + OpenSearch + Valkey for Agentic RAG”**
2. **“SpacesAI: Building Agentic Research with OCI OpenSearch and PostgreSQL”**
3. **“Valkey‑Accelerated RAG on OCI: The Polyglot Data Stack”**
4. **“OCI OpenSearch + PostgreSQL: The Open‑Source AI Retrieval Engine”**
5. **“From Upload to Answer: OCI’s Polyglot Stack for AI Search”**
6. **“Agentic Research on OCI: A Polyglot AI App with OpenSearch + Postgres”**
7. **“SpacesAI: The Open‑Source AI Stack (OCI Postgres • OpenSearch • Valkey)”**
8. **“OCI GenAI Meets OpenSearch: Architecting an AI‑Native Knowledge Platform”**
9. **“Polyglot AI Search: Postgres + OpenSearch + Valkey at Enterprise Scale”**
10. **“OCI‑Powered RAG: OpenSearch + PostgreSQL + Valkey in One Stack”**

### Tagline ideas (short + marketing friendly)
- **“OCI OpenSearch × PostgreSQL × Valkey — the AI‑native data stack.”**
- **“SpacesAI: Agentic research on the open‑source OCI stack.”**
- **“Polyglot RAG at scale with OCI GenAI.”**

---

## 10) Quick reference summary

- **Deep Research**: agentic planning + local retrieval + optional web + missing‑concept loops + LLM synthesis.
- **Text Search**: semantic, full‑text, hybrid, or RAG with OCI GenAI/OpenAI/Bedrock.
- **Image Search**: OpenCLIP embedding + tags + OCR caption for vector + text ranking.
- **Polyglot stack**: Postgres (truth), OpenSearch (retrieval), Valkey (speed), Object Storage (binaries).

---

If you want this guide expanded with real API payloads, config snippets, or benchmarking results, tell me what to add and I’ll extend it.