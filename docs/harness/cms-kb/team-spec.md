# CMS KB Harness Team Spec

## Summary

This harness uses a shallow pipeline for CMS documentation work: archive first, extract second, then review provenance before anything is treated as trusted output.

It is intentionally repo-local and markdown-driven. Version 1 does not add `AGENTS.md`, a supervisor backlog, or an autonomous experiment loop.

## Roles

- `cms-kb-orchestrator`: classifies the request, assigns the phase, and enforces handoff order.
- `cms-kb-archive`: discovers source pages, inventories assets, and records archive provenance.
- `cms-kb-extraction`: turns archived material into metadata, entities, and graph seeds.
- `cms-kb-parse`: parses HTML and PDF text and generates chunks with complete provenance.
- `cms-kb-qa`: checks citations, provenance, and completeness before downstream use.

## Handoff Contract

The harness uses deterministic `_workspace/` files so every phase can be inspected after the run.

- `_workspace/01_request.md`: request scope, source scope, and acceptance criteria.
- `_workspace/02_source_inventory.md`: discovered pages, files, and coverage notes.
- `_workspace/03_archive_manifest.md`: archive paths, checksums, and download provenance.
- `_workspace/04_extraction_pack.md`: extracted dataset, variable, and relationship records.
- `_workspace/05_parsing_pack.md`: parsed text paths and text chunk JSONs with full provenance.
- `_workspace/06_qa_review.md`: pass/fix/redo verdict with reasons and missing evidence.

Canonical durable outputs, when the repo later materializes writers, are `data/raw/`, `data/metadata/`, and `data/graph/`. The harness itself only depends on the markdown handoffs above.

## Failure Policy

- Archive failures stop the pipeline if a required source page cannot be reached or a file checksum cannot be recorded.
- Extraction failures stop the pipeline if the source document, source URL, or provenance trail is missing.
- QA failures return `fix` when the issue is local and bounded, or `redo` when the source set or extraction shape is wrong.
- No role is allowed to silently fill provenance gaps.

## Coordination Rules

- Keep the workflow sequential unless a future task explicitly adds a bounded parallel branch.
- Keep the review gate explicit; extraction output is not trusted until QA passes.
- Keep model-specific heuristics and retries out of the durable contract unless they are isolated enough to delete later.

## Scope Boundaries

- Do not add an experiment ledger in this harness version.
- Do not add a second coordination layer.
- Do not create repo-wide guidance files unless the repository later needs always-loaded instructions.

