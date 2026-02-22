# Changelog

All notable changes to this repository are documented in this file. Keep entries reverse-chronological and add the date (YYYY-MM-DD) for each change.

## 2026-02-21
- Added ImageSearchV2 enhancements: LLaVA/BLIP captioning, OCR tags, weighted image search, and image reindex CLI.
- Indexed OCR text into OpenSearch image documents and included OCR in Postgres image ranking.
- Ensured document deletions remove OpenSearch image entries and updated KB badges to show storage backend labels.
- Added captioning extras to build/start scripts and expanded image env configuration comments.
- Hid session titles in the sessions drawer list and added follow-up modal responses.
- Added Deep Research session list snippet for the first question and styled it in the sessions drawer.
- Improved first-question follow-up suggestions when local knowledge base hits are present.
- Tightened Deep Research web-search heuristics to trigger when local evidence is sparse or weak.
- Added stronger grounding guardrails to Deep Research synthesis and refinement prompts.
- Documented new Deep Research follow-up settings:
  - `DEEP_RESEARCH_FOLLOWUP_AUTOSEND` (auto-send chips on click)
  - `DEEP_RESEARCH_FOLLOWUP_RELEVANCE_MIN` (relevance threshold with tuning guidance)
- Fixed Deep Research local-source visibility by preserving space_id in doc_id reindexing.
- Normalized OpenSearch _score handling for Deep Research confidence heuristics.
- Fixed OpenSearch KNN query vector normalization to avoid string payloads in knn queries.
- Adjusted OpenSearch recency scale formatting to avoid fractional day parse errors.
- Fixed Deep Research ordered list rendering to display proper sequential numbering.

## 2026-02-22
- Implemented a mobile-first SaaS UI refresh with an iOS-ready layout and bottom navigation.
- Refined auth cards, search settings, upload flow, and progress list styling with updated typography and shadows.
- Reworked Knowledge Base entries into iOS table-style rows with separators and tighter metadata.
- Added micro-interactions (press states, fade/slide-in results, staggered result animations).
- Documented UI updates in UI.md.
- Added iOS PWA shell/tab layout styling with active tab states and screen headers.