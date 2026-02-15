## Phase 3 Test Plan — Image Search Mode & Caching

### Objective
Verify that image assets ingested in Phase 2 can be retrieved through the new `/api/image-search` endpoint and UI, respecting authentication, space scoping, Valkey cache revisions, and thumbnail rendering.

### Prerequisites
- Phase 1 & 2 migrations applied; sample image assets ingested with known tags/captions.
- OpenSearch `spacesai_images` index populated and accessible.
- Valkey running for cache/revision tracking.
- FastAPI app available locally (or via docker-compose) with a seeded user and space.

### Test Scenarios

1. **API Happy Path**
   - `POST /api/image-search` with `{ "query": "diagram", "top_k": 5 }`.
   - Expect 200 with `results` array containing rank/score, doc/image IDs, thumbnail/file paths, captions, and tags.
   - Validate returned `doc_id` matches ingested document; verify `thumbnail_path` exists on disk/OCI.

2. **Tag Filtering**
   - Call endpoint with `tags: ["policy"]` and ensure results only include assets tagged accordingly.
   - Confirm `_normalize_tags` handles whitespace and mixed casing via API payload variations.

3. **Vector Override**
   - Provide `vector` (mocked array) in the payload; ensure endpoint prioritizes the provided embedding by verifying adapter receives it (instrument logs or patch test double).
   - If vector omitted, confirm text query triggers `embed_image_texts()` exactly once.

4. **Cache Behavior**
   - Warm Valkey cache by invoking `/api/image-search` twice with identical inputs; second call should hit cache (inspect logs or measure latency).
   - Upload a new image (Phase 2 flow) and confirm `bump_revision("image", uid, space_id)` invalidates cache (third call should fetch fresh results).
   - Delete a document and ensure both `text` and `image` revisions bump.

5. **UI Integration**
   - Login via UI, switch to "Image Search" tab, enter query/tags, and verify cards render with thumbnails, captions, and badges.
   - Test "Preview size" dropdown (small/medium/large) adjusts card layout.
   - Upload reference image via UI field; ensure request is sent as `FormData` and results update accordingly.

6. **Error Handling**
   - Submit empty payload (no query/tags/vector) -> expect 400 with validation message.
   - Simulate OpenSearch downtime (stop service) and ensure API returns 500/503 with readable message while UI surfaces "Image search failed" toast.

7. **Regression**
   - Run existing `/api/search` (text) to confirm no regressions.
   - Execute Deep Research modal to ensure new tab logic doesn’t break prior UI controls.

### Acceptance Criteria
- API enforces auth/space isolation and returns accurate metadata.
- Cache invalidates upon image/text uploads/deletes per Valkey revision.
- Frontend presents image results responsively with accessible toggles.
- Error states are surfaced in both API responses and UI toasts/logs.