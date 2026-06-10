---
name: cms-kb-archive
description: Discover CMS documentation sources, inventory assets, and record archive provenance with deterministic manifests.
---

# CMS KB Archive Specialist

## When to use

- Use when the work needs source discovery, crawl coverage, downloads, or checksum capture.
- Use when the goal is to preserve raw CMS or ResDAC documentation before parsing or extraction.
- Do not use after the source set is frozen and the task is purely downstream extraction.

## Required inputs

- Entry URLs or source domains.
- Inclusion rules for pages, PDFs, spreadsheets, and attachments.
- Preservation requirements for raw HTML, filenames, and checksums.

## Workflow

1. Enumerate entry pages and linked documents.
2. Record every discovered URL in `_workspace/02_source_inventory.md`.
3. Capture archive location, checksum, media type, and download timestamp in `_workspace/03_archive_manifest.md`.
4. Preserve raw source files in the canonical raw archive location when the repo adds a writer for them.
5. Flag dead links, duplicate assets, and unreachable pages explicitly instead of skipping them.

## Expected outputs

- `_workspace/02_source_inventory.md`
- `_workspace/03_archive_manifest.md`
- Coverage notes for missing or dead sources.

## Validation notes

- Every archived file should be traceable to a source URL.
- Every source URL should either have a file, a dead-link note, or a deliberate exclusion reason.
- Checksums and timestamps are required for reproducibility.

## Stop conditions

- Stop if a file cannot be tied to a source URL.
- Stop if the archive would silently omit a known asset class.
- Stop if the source set changes after extraction has already started.

