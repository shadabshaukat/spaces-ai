# Phase 2 Test Plan — Image Ingestion

## Objective
Validate end-to-end image ingestion: metadata capture, embeddings/captions, storage (local + OCI), and indexing in Postgres/OpenSearch.

## Tests
1. **Vision Embedding Path**
   - Run ingestion on sample images via CLI/API; ensure `vision_embeddings.embed_image_paths` is invoked and produces vectors of `IMAGE_EMBED_DIM` length.
   - When embeddings are unavailable (e.g., model missing), ingestion must still persist metadata and log a warning without crashing.

2. **PostgreSQL Persistence**
   - After ingestion, query `image_assets` to verify rows include `document_id`, `user_id`, relative paths, tags/captions, and vector data (if DB storage enabled).
   - Inspect the parent `documents.metadata` field and confirm it now carries `image_tags`, `image_caption`, `thumbnail_path`, `thumbnail_object_url` (when OCI is enabled), and native dimensions.

3. **OpenSearch Indexing**
   - Confirm `ensure_image_index()` is called and `spacesai_images` contains documents for ingested images.
   - Use OpenSearch `_search` to validate stored metadata (tags, caption) and verify vector similarity queries return the ingested asset.

4. **Storage Outputs**
   - Verify thumbnails and original images exist under `UPLOAD_DIR` (and OCI bucket when enabled) using the relative paths saved to Postgres metadata.
   - For OCI mirroring, assert that a second object with `_thumb` suffix is created and accessible via a PAR URL.

5. **Error Handling**
   - Ingest malformed/non-image files; ensure ingestion skips gracefully and logs warnings (no document row created).
   - Simulate thumbnail upload failures (e.g., revoke OCI permissions) and confirm ingestion still succeeds locally while warning about remote sync.

6. **Regression**
   - Run existing text ingestion to ensure no regressions from new image code paths.
   - Execute `/api/search` to confirm chunk ingest/index flows remain unaffected.

## Acceptance Criteria
- Images are ingested without errors, generating embeddings and metadata.
- `image_assets` and OpenSearch index contain consistent records.
- Storage backend (local/OCI) receives files/thumbnails.
- Logging covers success/failure cases for auditing.