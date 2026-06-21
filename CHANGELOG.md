# CHANGELOG

## Unreleased

### Added
- Phase 11B: implemented dynamic cohort data dictionary generators querying the SQLite FTS5 backend (exposed via programmatic API and CLI subcommand).
- Archive progress logging now emits periodic rollup events, truncates the
  per-run JSONL log at start, flushes each append, and reads tails efficiently
  from large logs.
- `manifests/site_inventory_edges.csv` support for preserving many-to-many
  discovery provenance separately from URL-deduplicated inventory rows.
- Lightweight JSONL progress logging for inventory/archive runs, plus
  `cms-kb-progress` for summarizing recent progress events.
- Canonical ResDAC variable-page outputs:
  `data/metadata/canonical_variables.csv` and
  `data/graph/data_source_variable_edges.csv`.
- Comprehensive [user-manual.md](docs/user-manual.md) for health policy researchers, scientists, and analysts.
- Detailed [developer-guide.md](docs/developer-guide.md) for engineers, operators, and developers maintaining the pipeline.
- Phase 8: Model Context Protocol (MCP) server integration, exposing read-only tools for automated agent search and retrieval.
- `cms-kb-evaluate-variables` for seeded exact variable-name retrieval usefulness smoke checks.

### Changed
- Consolidated user-facing documentation into a unified, comprehensive [user-manual.md](docs/user-manual.md), deleting the redundant [pipeline.md](docs/pipeline.md).
- Added explicit user-facing guides on how to build and rebuild the knowledge base locally using the pre-packaged offline ResDAC archive snapshot under `data/raw/`.
- Updated all references to `pipeline.md` in README, ARCHITECTURE, and the archive module source code.
- Split documentation status tracking into separate code implementation,
  checked-in corpus, and derived artifact states.
- Clarified `SPEC.md` so `Past`, `Present`, and `Future` are mutually exclusive operational states, with completed pipeline phases moved out of active work.
- Treat transient inventory HTTP statuses as unresolved instead of dead links, and allow archive retries to reuse already preserved raw files.
- Inventory now records standalone ResDAC variable-detail pages linked from
  data-documentation tables, and archive preservation attempts those pages as
  raw HTML citation supplements.
- Variable extraction now recognizes HTML data-documentation table rows as
  definition evidence and prefers HTML citations over PDF evidence for exact
  variable retrieval.
- Agent context citations now include variable-detail URLs and populate local
  variable-detail documents from `manifests/archive_manifest.csv` when the
  standalone variable page is archived locally.
- Archive preservation now retries HTTP 429 responses politely and defers
  remaining standalone variable-page requests after repeated rate limits.

### Added
- Initial canonical project documentation with `SPEC.md`, `ARCHITECTURE.md`, and `CHANGELOG.md`.
- Repository-level architecture and scope notes for the CMS documentation knowledge base.
- Repository-level `LESSONS.md` for capturing recurring failure patterns and workflow lessons.
- Discovery-only CMS data inventory crawl with CSV output, workspace summary output, and live-site provenance capture.
- Phase 1 archive preservation CLI with raw HTML/asset downloads, archive manifest CSV output, and `_workspace/03_archive_manifest.md` handoff summary.
- Phase 2 metadata extraction CLI with checksum validation, dataset/document metadata CSV outputs, graph seed edges, and `_workspace/04_extraction_pack.md` handoff summary.
- Phase 3 document parsing CLI with HTML/PDF text extraction, chunking, and `_workspace/05_parsing_pack.md` handoff summary.
- Phase 4 QA Specialist CLI with checksum verification, URL mapping auditing, reference integrity checks, and `_workspace/06_qa_review.md` handoff summary.
- Phase 5 CMS Research Ontology with field normalization (program, category, availability) and graph nodes/edges seed extraction (belongs_to, related_to) plus QA auditing integration.
- Phase 6 variable-level metadata CLI with conservative parsed-chunk extraction, `variables.csv`, `variable_edges.csv`, and `_workspace/07_variable_pack.md` handoff summary.
- Phase 7 retrieval MVP CLI with deterministic lexical search over datasets, documents, variables, and parsed chunks while preserving source citations.
- Minimal agent-facing context CLI and Python API that wrap retrieval results in stable, citation-preserving output for downstream agent workflows.
