## SpacesAI Enhancement Phases

| Phase | Scope | Status |
| --- | --- | --- |
| Phase 1 | Schema/config updates for image + table storage, vision embedding plumbing, plan/test docs | ✅ Complete |
| Phase 2 | Image ingestion (embeddings + captions + storage) | ✅ Complete |
| Phase 3 | Image search mode (API + UI) & caching | ✅ Complete |
| Phase 4 | Deep Research agentic workflow + web search + confidence | 🚀 In QA |
| Phase 5 | Rich table extraction & APIs | ⬜ Pending |
| Phase 6 | Final QA, test plan execution, docs | ⬜ Pending |

---

### Phase 1 Summary

- ✅ Config/env settings for vision & tables.
- ✅ `init_db()` creates `image_assets` + `document_tables` tables.
- ✅ OpenSearch image index helper with replication/sharding.
- ✅ Vision embedding service (OpenCLIP loader).
- ✅ Test plan + docs updated.

> Phase 1 complete; proceed with Phase 2 implementation.

### Phase 2 Summary

- ✅ Image ingestion pipeline writes metadata to Postgres + OpenSearch.
- ✅ Thumbnails + original images stored locally/OCI with metadata pointers.
- ✅ Vision embeddings + captions generated via OpenCLIP, with graceful fallback logging.
- ✅ Valkey revision bumping ensures cache invalidation on upload/delete.

> Phase 2 complete; Phase 3 focuses on surfacing the images via API/UI search.

### Phase 3 Summary

- ✅ `/api/image-search` endpoint wired into Valkey cache + embedding helpers.
- ✅ Frontend tabs expose text vs. image search, responsive cards with captions/tags.
- ✅ Documentation/test plans refreshed (see PHASE3_TEST_PLAN.md).

> Phase 3 is complete; Phase 4 focuses on Deep Research upgrades.

### Phase 4 Summary

- ✅ Deep Research backend now uses `SmartResearchAgent` to selectively call web search, track confidence, and enforce configurable timeouts sourced from `.env`.
- ✅ API responses include `confidence`, `web_attempted`, elapsed seconds, and detailed references for local vs. web sources for full transparency.
- ✅ Frontend modal surfaces confidence/time/web badges plus separate reference sections so users can distinguish KB vs. external citations.
- ✅ Deep Research UI now renders ordered lists, code fences, and follow-up chips.
- ✅ OpenSearch recency weighting uses created_at decay (requires reindex for existing docs).
- ✅ Unit tests cover agentic heuristics, time-budget enforcement, and confidence scoring edge cases.
- ✅ Documentation refreshed (README, PHASE4 test plan) and a Postgres/OpenSearch MCP server was added so editors can run read-only diagnostics.

> Phase 4 code complete; QA focuses on running the Phase 4 test plan and final regression pass before Phase 5.