---
name: cms-kb-parse
description: Convert HTML and PDF documentation into clean text and metadata-bearing chunks with preserved provenance.
---

# CMS KB Parse Specialist

## When to use

- Use when raw HTML and PDF assets are archived and need to be parsed and chunked.
- Use when preparing document contents for indexing, searching, or vector retrieval layers.
- Do not use for initial crawling or raw archival tasks.

## Required inputs

- Extracted metadata files (`data/metadata/datasets.csv` and `data/metadata/documents.csv`).
- A clean archive manifest.
- Local raw HTML and PDF files under `data/raw/`.

## Workflow

1. Read input datasets and documents from metadata files.
2. Parse body text from HTML files using `trafilatura` and PDF pages using `pymupdf`.
3. Save clean parsed text to `data/parsed/html/` and `data/parsed/pdf/`.
4. Break parsed text into chunks (e.g. 500-1000 characters) with overlap.
5. Assign stable chunk IDs and write individual chunk JSONs under `data/parsed/chunks/` and a unified `chunks.jsonl`.
6. Write the parsing pack handoff summary to `_workspace/05_parsing_pack.md`.

## Expected outputs

- `_workspace/05_parsing_pack.md`
- Raw parsed text files under `data/parsed/`
- Chunk JSONs and consolidated `chunks.jsonl`

## Validation notes

- Every chunk must have a non-empty `text`, `source_document`, `url`, and `dataset` identifier.
- Page numbers must be captured accurately for PDF files.
- Chunk IDs must be stable and deterministic.

## Stop conditions

- Stop if a PDF contains only scanned images and requires OCR.
- Stop if a document cannot be mapped to any dataset ID.
- Stop if parsing logic encounters unhandled file types.
