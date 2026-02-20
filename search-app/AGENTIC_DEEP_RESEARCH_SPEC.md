# Agentic Deep Research Specification

This document describes the target workflow for a **true agentic Deep Research mode** in SpacesAI, plus LLM recommendations for large‑context, multi‑step reasoning on OCI GenAI and AWS Bedrock.

---

## 1. Goals

- Synthesize **local knowledge base**, **web evidence**, and **user‑provided URLs**.
- If a source is weak, automatically **replan + retry** with fallback queries.
- Capture missing concepts explicitly and loop back until coverage is acceptable.
- Provide a reliable research trail with ranked references.

---

## 2. Current Baseline (what exists now)

- Local hybrid retrieval (`hybrid_search`) on sub‑questions.
- Optional URL ingestion (crawl + chunk + embed) → conversation‑scoped context.
- Web search via DuckDuckGo HTML scrape.
- LLM synthesizes answer from aggregated contexts.

**Limitation:** It is mostly a single‑pass flow and does not replan or retry if evidence is weak.

### ✅ Specifications Availability (current implementation)

| Capability | Status | Notes |
| --- | --- | --- |
| Local KB hybrid retrieval | ✅ Available | `hybrid_search` sub‑questions |
| URL ingestion (crawl + embed) | ✅ Available | Conversation‑scoped external docs |
| Web search fallback | ✅ Available | DuckDuckGo HTML + lite fallback |
| Weak coverage detection | ✅ Available | Heuristic on hit count/doc diversity |
| LLM query rewrite | ✅ Available | Used when coverage is weak |
| Missing concept detection | ✅ Available | LLM‑driven gap analysis |
| **Missing concept multi‑turn loop** | ✅ Added | Re‑queries missing concepts (configurable) |
| **Grouped context synthesis** | ✅ Added | Local/URL/Web/Missing blocks |
| **Reference ranking** | ✅ Added | Local refs ranked by distance/score |
| **Per‑source confidence** | ✅ Added | Local/Web/URL confidence summary |
| **Recency‑aware ranking** | ✅ Added | Recency boost with configurable half‑life |
| **Follow‑up question prompts** | ✅ Added | Returned when confidence is low; surfaced as chips in DR UI |
| References output | ✅ Available | Local chunks + web refs |
| Clean non‑redirect web links | ✅ Available | DuckDuckGo normalized |

---

## 3. Target Agentic Workflow (upgraded)

### Step A — Planning
1. Create **sub‑questions** (2–4 max).
2. Identify **expected sources**: Local KB, Web, URLs.

### Step B — Local Retrieval
1. Run hybrid search for each sub‑question.
2. Compute coverage metrics:
   - Hit count
   - Unique document count
   - Best distance

### Step C — Weak Coverage Detection
If local coverage is weak:
- **Rewrite search query** with LLM into a short, direct search phrase.
- Retry local retrieval using rewritten query.

### Step D — Web Retrieval
If coverage still weak (or force_web):
- Run web search with the rewritten query.
- Use web hits as context + references.

### Step E — Missing Concepts Analysis
Use LLM to list missing concepts not covered by retrieved evidence.
- Add these missing topics into the context.
- Optionally loop (max 1–2 retries) to fetch more evidence. ✅ Implemented via missing‑concept loop.

### Step F — Synthesis
- LLM receives grouped contexts:
  - Local KB
  - URL evidence
  - Web evidence
  - Missing concepts list
- Respond with structured synthesis. ✅ Implemented with grouped context blocks.

### Step G — Reference Output
- Rank and return evidence by source.
- Provide clean, non‑redirect web links.
  - ✅ Implemented with local ref ranking + per‑source confidence metadata.

---

## 4. Implementation Notes (already added)

- **Query rewrite** with LLM for weak coverage.
- **Missing concept detection** with LLM.
- **Fallback web search** always uses rewritten query when available.
- **Web search resilience** with DuckDuckGo lite fallback.
- **Missing concept loop** for 1–N additional retrieval passes (configurable).
- **Grouped context blocks** for synthesis.
- **Per‑source confidence** (local/web/url) in DR metadata.
- **Local reference ranking** by distance/score.
- **Recency‑aware ranking** with configurable half‑life.
- **Follow‑up question prompts** when confidence is low (rendered as clickable UI chips).
- **Deep Research renderer** supports code fences and ordered lists.
- **OpenSearch recency weighting** via function_score decay on `created_at`.

---

## 5. Environment Variables (Deep Research)

These controls tune the agentic workflow (see `.env.example` for full annotations):

- `DEEP_RESEARCH_TIMEOUT_SECONDS`: total DR time budget.
- `DEEP_RESEARCH_LOCAL_TOP_K`: local chunks per subquestion.
- `DEEP_RESEARCH_WEB_TOP_K`: web hits when web search triggers.
- `DEEP_RESEARCH_URL_MAX_DEPTH` / `DEEP_RESEARCH_URL_MAX_PAGES`: URL crawl scope.
- `DEEP_RESEARCH_RETRY_LOOPS`: web decision retries on low confidence.
- `DEEP_RESEARCH_CONFIDENCE_THRESHOLD`: minimum confidence to stop retrying (lower = more retries, higher = faster).
- `DEEP_RESEARCH_MISSING_CONCEPT_LOOPS`: missing‑concept retrieval passes (0 disables).
- `DEEP_RESEARCH_MISSING_CONCEPT_TOP_K`: max missing‑concept subqueries per loop.
- `DEEP_RESEARCH_RECENCY_BOOST`: weight added to newer sources in ranking.
- `DEEP_RESEARCH_RECENCY_HALF_LIFE_DAYS`: half‑life for recency decay.
- `DEEP_RESEARCH_FOLLOWUP_ENABLE`: enable follow‑up prompts.
- `DEEP_RESEARCH_FOLLOWUP_THRESHOLD`: confidence below this triggers follow‑ups.
- `DEEP_RESEARCH_FOLLOWUP_MAX_QUESTIONS`: cap follow‑up questions returned.

---

## 6. Minimalist UX Guidance (Reasoning/Agentic UI)

**Goal:** keep the main answer clean while showing optional “research steps” in muted UI.

### Suggested HTML snippet (minimal, collapsible)
```html
<details class="dr-insight">
  <summary>
    <span class="pill-badge pill-source">Research steps</span>
    <span class="muted">Tap to view plan, coverage, and confidence</span>
  </summary>
  <div class="dr-insight-body">
    <div class="muted">Plan: 3 sub‑questions</div>
    <div class="muted">Local KB: 22 chunks / 4 docs</div>
    <div class="muted">Web: 6 hits</div>
    <div class="muted">Missing concepts: 3</div>
    <div class="muted">Confidence: 0.62 (Local 0.75 / Web 0.4 / URL 0.6)</div>
  </div>
</details>
```

### Suggested CSS (light‑grey, unobtrusive)
```css
.dr-insight {
  margin-top: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fafafa;
}
.dr-insight > summary {
  list-style: none;
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  gap: 8px;
  align-items: center;
}
.dr-insight-body {
  padding: 8px 12px 12px;
  display: grid;
  gap: 4px;
  color: #6b7280;
  font-size: 12px;
}
```

### Implementation note
- Use the `deep_research_steps` metadata and the new `source_confidence` + `followup_questions` payload to populate this panel.
- Keep it collapsed by default to avoid distracting users.

### Implemented DR UI behaviors
- Ordered list numbering uses browser `<ol>` numbering (fixes 1/1/1 issue).
- Code fences render as `<pre><code>` blocks with optional language trimmed.
- Follow-up questions render as clickable chips that insert text into the composer.

---

## 7. Recommended LLMs for Agentic Deep Research

### OCI GenAI (Oracle)
Recommended for large context and multi‑step reasoning:

- **Cohere Command R+ (OCI GenAI)**
  - Strong retrieval‑augmented reasoning
  - Large context window
  - Optimized for tool use and long‑form synthesis

- **Llama 3.1 70B (OCI GenAI)**
  - Strong general reasoning
  - Long context support

### AWS Bedrock
Recommended for deep research synthesis:

- **Anthropic Claude 3.5 Sonnet / Claude 3 Opus**
  - Strong multi‑step reasoning
  - Large context window
  - Excellent summarization + synthesis

- **Cohere Command R / R+**
  - Retrieval‑focused agentic reasoning
  - Good for long‑form answers

### Selection Guidance
- **Best reasoning + synthesis:** Claude 3.5 Sonnet / Opus
- **Best retrieval‑augmented flow:** Command R+
- **Balanced and cost‑effective:** Llama 3.1 70B

---

## 8. Future Enhancements (optional)

- Evidence ranking with embedding similarity + source authority signals.
- Optional auto-generated follow-up actions (e.g., "Run again" button).
- Persist OpenSearch `created_at` for existing docs via reindex (required after new mapping fields).

---

## 9. Success Criteria

- Answers always blend **local + web + URL** evidence when available.
- If any source is weak, the agent retries with better search queries.
- Missing topics are explicitly detected and covered in synthesis.
- References always returned and contain valid URLs.

***

This specification is the reference design for a premium agentic Deep Research mode in SpacesAI.
***