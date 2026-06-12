# ARCHITECTURE

## Overview
The repository is a documentation-first knowledge base for CMS and ResDAC materials. The canonical repo state is the archived source material, extracted metadata, parsed chunks, graph seed files, retrieval outputs, and provenance-bearing manifests produced by the local pipeline.

Last Reviewed: 2026-06-12
Status: Verified

## Main Surfaces
- `README.md`: first-visitor overview, quick start, and documentation map.
- `docs/pipeline.md`: phase commands, generated outputs, and QA workflow.
- `docs/data-model.md`: dataset, document, variable, graph, and provenance records.
- `docs/source-coverage.md`: current ResDAC source scope and future source families.
- `SPEC.md`: operational feature-state record with mutually exclusive Past, Present, and Future sections.
- `ROADMAP.md`: strategic phase history and future direction for archive, extraction, parsing, graph, retrieval, and evaluation work.
- `docs/harness/cms-kb/team-spec.md`: repo-local orchestration contract for archive, extraction, and QA handoffs.
- `data/`: canonical durable outputs, especially raw archives, parsed text, metadata, and graph artifacts.
- `manifests/`: inventory and provenance manifests for downloaded or parsed sources.
- `src/`: implementation surface for crawl, archive, parse, metadata, graph, retrieval, and evaluation code.
- `tests/`: verification for archive integrity, extraction accuracy, and retrieval behavior.

Last Reviewed: 2026-06-12
Status: Verified

## Data Flow
1. Discover source pages and files from ResDAC and related CMS documentation sites.
2. Archive raw HTML, PDFs, spreadsheets, and attachments with checksums and source URLs.
3. Extract structured metadata and relationships from the archived corpus.
4. Persist provenance-bearing artifacts in `data/`, `manifests/`, and related stores.
5. Expose search and retrieval layers that always retain citations back to source documents.

Last Reviewed: 2026-06-12
Status: Verified

## Constraints
- Preserve source material before transforming it.
- Keep provenance attached to every derived record.
- Favor small, composable pipeline steps over hidden cross-cutting logic.
- Treat `data/raw/` and manifest outputs as canonical inputs to downstream extraction.
- Do not introduce retrieval outputs that cannot be traced back to a source document.

Last Reviewed: 2026-06-12
Status: Verified

## Current State
Phase 0 discovery is implemented in `src/cms_kb/inventory.py`. The `cms-kb` CLI crawls ResDAC listing pages, follows dataset and documentation links, probes linked assets, and writes:

- `manifests/site_inventory.csv`: machine-readable inventory rows.
- `_workspace/02_source_inventory.md`: human-readable coverage summary for harness handoffs.

Phase 1 archive preservation is implemented in `src/cms_kb/archive.py`. The `cms-kb-archive` CLI consumes the inventory CSV, downloads live HTML pages and live linked assets, and writes:

- `data/raw/html/...`: archived listing, dataset, and documentation page HTML.
- `data/raw/assets/...`: archived asset files grouped by asset kind.
- `manifests/archive_manifest.csv`: archive provenance rows with URL, status, checksum, timestamp, and local path.
- `_workspace/03_archive_manifest.md`: archive handoff summary for downstream phases.

Phase 2 metadata extraction is implemented in `src/cms_kb/extraction.py`. The `cms-kb-extract` CLI consumes archived rows from `manifests/archive_manifest.csv`, verifies local files and checksums, and writes:

- `data/metadata/datasets.csv`: dataset records extracted from archived dataset pages.
- `data/metadata/documents.csv`: documentation page and asset records linked to datasets.
- `data/graph/document_edges.csv`: graph seed edges from datasets to documents.
- `data/graph/ontology_nodes.csv`: dataset and program ontology seed nodes.
- `data/graph/ontology_edges.csv`: ontology seed relationships such as `belongs_to` and `related_to`.
- `_workspace/04_extraction_pack.md`: extraction handoff summary with unresolved normalization notes and failures.

Phase 3 document parsing is implemented in `src/cms_kb/parsing.py`. The `cms-kb-parse` CLI consumes dataset and document metadata, parses HTML/PDF text, chunks extracted text, and writes:

- `data/parsed/html/...`: parsed HTML text.
- `data/parsed/pdf/...`: parsed PDF text.
- `data/parsed/chunks/...`: per-chunk JSON metadata.
- `data/parsed/chunks.jsonl`: unified chunk stream with source document, page, dataset, and URL provenance.
- `_workspace/05_parsing_pack.md`: parsing handoff summary with failures.

Phase 4 QA is implemented in `src/cms_kb/qa.py`. The `cms-kb-qa` CLI validates checksums, source URLs, local paths, dataset/document references, ontology references, and optional variable outputs, then writes:

- `_workspace/06_qa_review.md`: pass/fix/redo verdict with finding details.

Phase 5 CMS Research Ontology is implemented as part of extraction and QA. It normalizes program, category, and availability fields and writes ontology seed nodes and edges for program, category, availability, `belongs_to`, and `related_to` relationships.

Phase 6 variable-level metadata extraction is implemented in `src/cms_kb/variables.py`. The `cms-kb-variables` CLI consumes parsed chunks, extracts conservative variable records only when definition evidence is present, and writes:

- `data/metadata/variables.csv`: variable records with dataset, definition, aliases, years, source document, source URL, page, and chunk provenance.
- `data/graph/variable_edges.csv`: dataset-to-variable `contains` edges with chunk provenance.
- `_workspace/07_variable_pack.md`: variable extraction handoff summary with skipped candidates and failures.

Phase 7 retrieval MVP is implemented in `src/cms_kb/retrieval.py`. The `cms-kb-search` CLI performs deterministic lexical search over dataset, document, variable, and parsed chunk records, returning stable result fields with `source_url` citations and local source document/page provenance when available.

Agent-facing API layers are not implemented yet. The harness contract in `docs/harness/cms-kb/team-spec.md` defines how phases should hand off provenance-bearing artifacts.

Last Reviewed: 2026-06-12
Status: Verified
