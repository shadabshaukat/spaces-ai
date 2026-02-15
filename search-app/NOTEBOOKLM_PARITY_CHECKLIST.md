## NotebookLM Parity Checklist

This document distills the active NotebookLM-style goals, highlights what already shipped in this iteration, and calls out the next actions required for parity. Use it as a living tracker alongside `NOTEBOOKLM_ROADMAP.md`.

### 1. Goals Recap

1. Deep Research UX should mirror NotebookLM’s progressive disclosure: hide noisy UI until the user opts in, show collapsible chunk details, and clearly label experimental features.
2. Web research must be deterministic—users should understand when the agent hit the public web versus staying local (force-web override when needed).
3. Surface all NotebookLM-parity asks (timeline, dual-pane layout, notebook artifacts, etc.) in one reference doc for prioritization.

### 2. Delivered This Cycle

| Area | Change | Status |
| --- | --- | --- |
| DR Modal UX | Collapsible Sources deck that hides local and web evidence until expanded; chunk cards themselves are `<details>` to keep noise low. | ✅ |
| Chunk Presentation | Added per-chunk details accordion (title, chunk #, actions) and Beta badge on Image tab to align with NotebookLM’s progressive disclosure. | ✅ |
| Image Search Labeling | “Image Search” tab and helper text now carry a Beta badge so users understand maturity. | ✅ |
| Web Link Reliability | URLs returned from Deep Research now run through `normalizeUrl()` so protocol-less DuckDuckGo links render correctly. | ✅ |
| Force-Web Control | UI toggle wired through `/api/deep-research/ask` → `deep_research.ask()` → `decide_web_and_contexts()` so users can guarantee web crawling (set or unset per prompt). | ✅ |
| Status Messaging | `drWebStatus` copy clarifies whether the latest answer pulled public web or stayed local. | ✅ |

### 3. Upcoming (NotebookLM Parity Targets)

1. **Conversation Timeline & Outline** – Persist prompt/response outline on the left rail; allow renaming and jumping between steps.
2. **Dual-Pane Layout** – Split answers (left) and expandable sources/notebook artifacts (right) similar to NotebookLM.
3. **Plan Editing & Sub-Question Control** – Expose the agent’s sub-queries; let users pause web fetches, reorder steps, or supply their own.
4. **Notebook Artifacts** – Provide a tab to pin highlights/quotes/TODOs with citations, plus export (Markdown/PDF/Google Docs).
5. **Instrumentation** – Emit telemetry for when web search triggers, how long each phase takes, and cache hits, to debug inconsistent runs.
6. **Image + Text Fusion** – Show relevant images inline with DR answers or notebook artifacts (respecting privacy boundaries).

### 4. Validation / QA Notes

- ✅ `tests/test_agentic_research.py` confirms `force_web` flows through the agent and honors low-budget skips (with `PYTHONPATH` including repo + `search-app`).
- ⚠️ Manual smoke test still recommended: open Deep Research modal, ask a question twice (with and without toggle) to verify the UI status string flips accordingly and sections stay collapsed by default.
- ⚠️ Track FastAPI lifespan warning when app boots; plan a follow-up refactor to the new lifespan handlers.

### 5. Next Steps Checklist

1. Add instrumentation (logs/metrics) for `force_web` usage and fallback reasons.
2. Design mock for dual-pane DR workspace; ensure it still fits within current CSS constraints.
3. Prototype notebook artifacts storage model (likely tied to `spaces` table) and export endpoints.
4. Explore timeline/outline UI component before introducing more complex plan-editing controls.

_Last updated: 2026-02-16_