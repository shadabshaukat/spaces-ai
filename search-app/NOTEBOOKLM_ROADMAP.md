## NotebookLM Parity Roadmap

This document tracks the features required to bring SpacesAI’s Deep Research and Knowledge Base experiences closer to Google’s NotebookLM. Items are grouped by experience area with suggested sequencing.

### 1. Deep Research Experience

1. **Conversation Timeline & Session Persistence**  
   - Introduce a left-hand timeline listing every prompt/response pair.  
   - Enable renaming steps, collapsing older turns, and restoring the full session when reopening Deep Research (per space).

2. **Dual-Pane Research Workspace**  
   - Keep the narrative / agent replies on the left while dedicating the right pane to “Sources.”  
   - Provide Local vs Web filters, quick actions (add to notebook, cite, summarize), and consistent color schemes.

   _Recent updates_: DR responses now render ordered lists, code fences, and follow-up chips in the existing modal; these should carry forward into the dual-pane layout.

3. **Plan View & Sub-Question Management**  
   - Surface the agent’s auto-generated plan similar to NotebookLM’s “Outline.”  
   - Allow users to edit plan steps, pause/resume web crawling, or inject custom sub-questions.

4. **Notebook Artifacts**  
   - Add a persistent “Notebook” tab where users can pin key findings, quotes, outlines, or TODOs harvested from answers.  
   - Each artifact links back to the source chunk or web page with citation metadata.

5. **Sharing & Export**  
   - Offer export options (Markdown, Google Docs, PDF) with citations.  
   - Provide shareable space-bound links so teammates can view the curated notebook.

### 2. Knowledge Base / Document Management

1. **Document Storyboards** – Display per-document summaries, highlights, related questions, and associated notebook entries.  
2. **Richer Filtering & Sorting** – Add filters for source type, tags, upload date, embedding status, and ingestion health.  
3. **Annotation Layer** – Let users annotate chunks or image assets directly, feeding into the notebook artifacts.  
4. **Change Tracking** – Surface when documents were updated or re-ingested, providing diff views for summaries.

### 3. Image Search Direction

1. **Clarify Use Case** – Decide whether images serve primarily as document previews or as standalone knowledge objects. This drives ranking heuristics.  
2. **Inline Notebook Integration** – Surface relevant images alongside text chunks in Deep Research responses and Notebook artifacts.  
3. **Faceted Browsing** – Add tag, document, and recency filters plus quick toggles (e.g., “remote only”, “AI-generated”).  
4. **Feedback Loop** – Capture thumbs up/down to refine CLIP embeddings or rerankers over time.  
5. **External Web Images (Optional)** – If we need NotebookLM-like web imagery, explore Google Custom Search or OCI Vision integrations, clearly separating public images from private KB assets.

### 4. Platform & Reliability

1. **Consistent Web Search Triggering** – Ensure Deep Research always attempts web retrieval when appropriate, with clear messaging when it falls back to local-only answers.  
2. **Instrumentation & Observability** – Log plan execution, search backend choice, and failure reasons to help debug inconsistent experiences.  
3. **Feature Flags & Beta Labels** – Maintain feature toggles (e.g., Image Search Beta) so experimental experiences can be rolled out safely.

---

Use this roadmap as a living document—update it as features ship or priorities shift toward full NotebookLM parity.