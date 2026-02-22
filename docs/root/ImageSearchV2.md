# ImageSearchV2

## Overview
ImageSearchV2 upgrades SpacesAI image ingestion and retrieval to improve semantic understanding, captions, and ranking across both Postgres and OpenSearch backends.

## What’s Added
- **Stronger image embeddings** (OpenCLIP ViT-L/14 by default).
- **Captioning pipeline** using LLaVA with a lightweight **BLIP** fallback for CPU.
- **OCR extraction** to capture text inside images.
- **Weighted hybrid ranking** (vector similarity + caption/tags) for Postgres and OpenSearch.
- **Batch re-embed CLI** to reprocess existing images.
- **UI cleanup** removing “Object copy” from image cards.

## Components & Specs

### 1) Image Embeddings
- **Model**: `IMAGE_EMBED_MODEL` (default: `openclip/ViT-L-14`)
- **Dimension**: `IMAGE_EMBED_DIM` (default: `768`)
- **Device**: `IMAGE_EMBED_DEVICE` (`cpu` / `cuda` / `mps`)
- Stored in `image_assets.embedding` and OpenSearch image index.

### 2) Captioning
- **Primary model**: `IMAGE_CAPTION_MODEL` (default: `llava-hf/llava-1.5-7b-hf`)
- **Small model**: `IMAGE_CAPTION_MODEL_SMALL` (default: `Salesforce/blip-image-captioning-base`)
- **Switch**: `IMAGE_CAPTION_USE_SMALL=true` for CPU-friendly captions
- **Prompt**: `IMAGE_CAPTION_PROMPT`
- **Timeout**: `IMAGE_CAPTION_TIMEOUT_S`
- Captions stored in:
  - `image_assets.caption`
  - `documents.metadata.image_caption`
  - `documents.metadata.image_caption_source`
  - `documents.metadata.image_caption_fallback`

### 3) OCR Tags
- OCR text extracted via `pytesseract`.
- OCR tokens added to `image_tags` for richer metadata search.
- Full OCR string stored in `documents.metadata.image_ocr_text`.

### 4) Weighted Image Search
Hybrid scoring combines vector similarity and caption/tags:

- **OpenSearch**: `function_score` over KNN + `multi_match`
- **Postgres**: weighted order over `distance` + `text_rank`

Weights are configurable:
- `IMAGE_SEARCH_VECTOR_WEIGHT` (default: 0.7)
- `IMAGE_SEARCH_TEXT_WEIGHT` (default: 0.3)

### 5) Batch Re-embedding CLI
Command:
```
uv run reindeximages --limit 1000 --reset
```
Options:
- `--user-id` / `--space-id`
- `--limit` / `--offset`
- `--reset` to delete existing rows
- `--dry-run` to preview

## Completed Checklist
- [x] LLaVA captioning pipeline integrated in ingestion
- [x] BLIP small-model fallback for CPU
- [x] OCR tagging added
- [x] Weighted vector + caption ranking (Postgres + OpenSearch)
- [x] CLI to reprocess existing image assets
- [x] Updated .env.example with full image env documentation
- [x] Removed “Object copy” from image cards

## Notes
- LLaVA on CPU can be slow; use BLIP if ingest latency is an issue.
- Rebuilding the image index is required when switching embedding models.