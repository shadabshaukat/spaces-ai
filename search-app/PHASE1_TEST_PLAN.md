# Phase 1 Test Plan

## Objective
Validate schema/config changes, vision embedding plumbing, and image/table index scaffolding for the SpacesAI enhancements.

## Tests
1. **Config Loading**
   - Set new env vars (e.g., `IMAGE_EMBED_MODEL`, `IMAGE_EMBED_DIM`, `ENABLE_IMAGE_STORAGE`, `ENABLE_TABLE_STORAGE`, `IMAGE_INDEX_NAME`).
   - Run `uv run python -c "from app.config import settings; print(settings.image_embed_model, settings.enable_table_storage)"` to verify values.

2. **Database Initialization**
   - Run `uv run python -c "from app.db import init_db; init_db()"` against a clean PostgreSQL instance.
   - Inspect schema to confirm `image_assets` and `document_tables` exist with expected columns and pgvector dimensions.
   - Repeat on an existing DB snapshot to ensure `CREATE IF NOT EXISTS` paths succeed without data loss.

3. **OpenSearch Image Index Template**
   - Execute the new helper (`OpenSearchAdapter().ensure_image_index()`).
   - Use `curl` or `opensearch-py` to inspect index settings and confirm shard/replica counts align with config (`IMAGE_INDEX_SHARDS`, `IMAGE_INDEX_REPLICAS`).

4. **OpenSearch recency mapping sanity check (if enabled)**
   - If OpenSearch is configured, verify the chunks index mapping includes `created_at` for recency scoring.

5. **Vision Embedding Loader**
   - Run `uv run python -c "from app.vision_embeddings import embed_image_paths; print(embed_image_paths([]))"` to verify module import without downloads.
   - Add unit tests (future) that mock `open_clip` to confirm caching + device selection.

6. **Documentation & Tracking**
   - Confirm `PHASES.md` reflects Phase 1 status.
   - Ensure this test plan lives alongside other phase docs.

7. **Regression Smoke Test**
   - Run `uv run pytest tests/test_api_smoke.py` to ensure base API remains functional after schema/config additions.

## Acceptance Criteria
- New config options load correctly with defaults and overrides.
- `init_db()` creates the new tables with correct pgvector dimensions.
- `ensure_image_index()` provisions the OpenSearch index template with desired replication/sharding.
- Vision embedding loader imports successfully (and gracefully handles missing models until downloaded).
- Documentation (PHASES + test plans) up to date.