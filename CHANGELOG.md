# CHANGELOG

## Unreleased

### Added
- Comprehensive [user-manual.md](docs/user-manual.md) for health policy researchers, scientists, and analysts.
- Detailed [developer-guide.md](docs/developer-guide.md) for engineers, operators, and developers maintaining the pipeline.
- Phase 8: Model Context Protocol (MCP) server integration, exposing read-only tools for automated agent search and retrieval.

### Changed
- Split documentation status tracking into separate code implementation,
  checked-in corpus, and derived artifact states.
- Clarified `SPEC.md` so `Past`, `Present`, and `Future` are mutually exclusive operational states, with completed pipeline phases moved out of active work.
- Treat transient inventory HTTP statuses as unresolved instead of dead links, and allow archive retries to reuse already preserved raw files.

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
