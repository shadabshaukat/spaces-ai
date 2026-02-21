# Changelog

All notable changes to this repository are documented in this file. Keep entries reverse-chronological and add the date (YYYY-MM-DD) for each change.

## 2026-02-21
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