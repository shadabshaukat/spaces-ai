## Phase 4 Test Plan — Deep Research Agentic Workflow & MCP Diagnostics

### Objective
Validate that Deep Research mode behaves agentically: planning sub-queries, selectively using web search, emitting confidence scores and reference metadata, respecting timeout budgets, and surfacing the UX cues. Also verify the Postgres/OpenSearch MCP server enables read-only diagnostics.

### Prerequisites
- Phase 1–3 features deployed and functioning (image ingestion/search, cache revisions).
- `.env` configured with `DEEP_RESEARCH_TIMEOUT_SECONDS` (e.g., 120) and a web provider key (SERPAPI/Bing) if available.
- FastAPI app running locally or on a test VM with seeded documents.
- Optional: valid SerpAPI/Bing keys to exercise live web fetch; otherwise mock responses.
- MCP server environment vars populated (`DATABASE_URL`, `OPENSEARCH_HOST`, etc.) and virtualenv dependencies installed.

### Test Scenarios

1. **Conversation bootstrap**
   - Call `POST /api/deep-research/start` and ensure a conversation_id is returned and cached.
   - Verify Valkey stores the state (fallback to in-process if cache disabled).

2. **Agentic planning + KB retrieval**
   - Ask a compound question via `/api/deep-research/ask`.
   - Confirm logs show `_extract_subqueries` splitting prompts and `hybrid_search` executed for each.
   - Ensure response references include at least one local chunk when KB data exists.

3. **Selective web invocation**
   - Provide a question outside the KB scope (e.g., "Summarize the latest GDPR amendments in 2024").
   - Expect `web_attempted=true` and references contain web entries.
   - With `DEEP_RESEARCH_WEB_SEARCH_PROVIDER=none`, confirm `web_attempted=false` even when KB has no hits.

4. **Timeout budgeting**
   - Set `DEEP_RESEARCH_TIMEOUT_SECONDS=20` temporarily.
   - Trigger a long-running request (mock slow OpenSearch or web provider) and ensure the response returns with `elapsed_seconds` near the budget and no hang.
   - Confirm `decide_web_and_contexts` receives a decreasing `max_seconds` and short-circuits when budget is exhausted (inspect logs or add instrumentation).

5. **Confidence scoring**
   - Compare answers with strong KB context vs. zero context. Expect higher `confidence` for the former (>0.7) and lower for the latter.
   - Force the fallback path (no LLM response) and ensure confidence does not exceed baseline.

6. **UI badges + references**
   - Use the web UI Deep Research modal.
   - Submit a query and verify:
     - Confidence badge color matches thresholds (green >=0.75, amber 0.4–0.74, red <0.4).
     - Time badge reflects `elapsed_seconds`.
     - Web badge toggles when `web_attempted=true`.
     - Local references list document IDs/chunk indices; web references display titles/URLs.
     - Ordered lists display sequential numbering and code fences render as formatted blocks.
    - Follow-up questions appear as chips that auto-send the suggested prompt.

7. **Caching + conversation continuity**
   - Ask multiple follow-up questions within the same conversation.
   - Ensure `_load_state` restores context and `recent_snippet` influences retrieval.
   - Validate state trimming keeps only the latest ~40 messages.

8. **MCP server — SQL tool**
   - Activate the MCP virtualenv and run `python main.py`.
   - From an MCP-capable client, list tools and locate "SpacesAI SQL (SELECT only)".
   - Execute a sample query (`SELECT id, email FROM users LIMIT 5`). Confirm rows return and non-SELECT statements are rejected with a clear error.

9. **MCP server — OpenSearch tool**
   - Invoke "SpacesAI OpenSearch query" with the chunks index and a `match` query.
   - Validate JSON hits mirror what OpenSearch `_search` returns.
   - Attempt a knn payload and confirm vector params pass through.

10. **Regression checks**
    - Run existing Phase 3 UI/API smoke tests to ensure no regressions in image search or core search flows.
    - Execute `pytest tests/test_agentic_research.py` to validate unit coverage.
    - Run `uv run reindexcli --email <user>` to validate OpenSearch recency reindexing path.

### Acceptance Criteria
- Deep Research responses consistently include confidence/time/web metadata and accurate references.
- Agent only performs web lookups when heuristics deem it necessary (configurable provider + timeout honored).
- UI faithfully mirrors backend metadata and keeps local vs. web citations distinct.
- MCP server tools operate read-only, assisting debugging without granting write access.
- Core regression suite remains green.