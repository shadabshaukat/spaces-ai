# Changelog

All notable changes to this repository are documented in this file. Keep entries reverse-chronological and add the date (YYYY-MM-DD) for each change.

## 2026-02-21
- Documented new Deep Research follow-up settings:
  - `DEEP_RESEARCH_FOLLOWUP_AUTOSEND` (auto-send chips on click)
  - `DEEP_RESEARCH_FOLLOWUP_RELEVANCE_MIN` (relevance threshold with tuning guidance)
- Fixed Deep Research local-source visibility by preserving space_id in doc_id reindexing.
- Normalized OpenSearch _score handling for Deep Research confidence heuristics.