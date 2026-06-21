# SPEC

This file is the operational feature-state record for the repository.
`Past`, `Present`, and `Future` are mutually exclusive by construction:
each feature or work item belongs to exactly one section at a time.
Use `STATUS.md` for the separate current status of code implementation,
checked-in corpus coverage, and retained generated data artifacts.

- `Past`: completed and verified work.
- `Present`: active implementation or refinement only. Keep this section small.
- `Future`: planned or desired work that is not currently active.

## Past
- Initial canonical documentation bootstrap completed.
- Phase 0 inventory discovery is implemented and writes machine-readable and workspace inventory outputs.
- Phase 1 archive preservation is implemented and writes raw HTML/assets plus an archive manifest and workspace summary.
- Phase 2 metadata extraction is implemented for archived dataset pages, documentation pages, and assets, with checksum validation and provenance-bearing CSV outputs.
- Phase 3 document parsing is implemented, parsing text from HTML/PDFs and generating text chunks with preserved provenance.
- Phase 4 QA Specialist is implemented, performing checksum and url checks to audit provenance, reporting to _workspace/06_qa_review.md.
- Phase 5 CMS Research Ontology is implemented, normalizing program, category, and availability fields from HTML, and extracting graph node and edge seeds (belongs_to, related_to) with QA validation.
- Phase 6 variable-level metadata extraction is implemented, deriving conservative variable records from parsed chunks and writing provenance-bearing variable metadata and graph edges.
- Phase 7 retrieval MVP is implemented, performing deterministic local lexical search over datasets, documents, variables, and parsed chunks while preserving source citations.
- Exact variable retrieval now prefers HTML data-documentation evidence when available, and a seeded variable-name smoke evaluation CLI checks snippet usefulness and citation presence.
- Minimal agent-facing context API is implemented, exposing retrieval results as citation-preserving Pydantic models and JSON CLI output.
- Agent context variable citations resolve archived standalone variable-detail pages from the archive manifest when those pages are available locally.
- Inventory now preserves many-to-many discovery edges separately from
  URL-deduplicated inventory rows, archive preservation emits progress logs and
  handles repeated rate limits politely, and variable extraction writes
  canonical ResDAC variable graph artifacts when archived variable-detail pages
  are available.
- Documentation state model clarified so Past, Present, and Future are mutually exclusive and completed phases no longer appear as active work.
- Phase 8: MCP Agent Integration is implemented, exposing read-only MCP server and tools (search_datasets, search_documents, search_variables, search_chunks, get_agent_context) over the retrieval API.
- Comprehensive end-user manual ([user-manual.md](docs/user-manual.md)) and developer guide ([developer-guide.md](docs/developer-guide.md)) created and linked to README.md.
- User manual revised and unified. Consolidated `docs/pipeline.md` and `docs/user-manual.md`, added offline build instructions, and updated references.
- Phase 10A is implemented: a deterministic, rebuildable SQLite FTS5 serving index over validated retrieval records is built, preserving `SearchResult`, CLI, agent-context, MCP, citation, exact-identifier, and deterministic-ordering behavior.
- Extended `scripts/benchmark_retrieval.py` into the offline-by-default performance and retrieval-quality evaluation gate for the SQLite backend, verifying sub-10ms warm latency and zero regressions in ranked results and citations.
- Phase 10B-C is implemented: optional hybrid retrieval and ranking is added via candidate semantic reranking from pre-computed SQLite embeddings. The pipeline preserves deterministic citation outputs, exact identifier query reliability, and handles library fallbacks gracefully.
- Phase 9: Package Distribution (PyPI) is implemented, bundling pre-built index database, CSV metadata, graph edges, and optimized HTML assets inside the module package. Resolved dynamically at runtime via importlib.resources and size-optimized to stay below the 100MB upload limit.
- Phase 11A is implemented: programmatic schema crosswalking and dataset availability query helpers (with year availability parsing and a custom CLI subcommand cms-kb-integration).


## Present
- None.

## Future
Future work is organized as implementation phases. A phase may be promoted into
`Present` when active work begins, with concise verification criteria and
explicit out-of-scope notes.

### Phase 11: Downstream Integration APIs
Purpose: provide standard programmatic APIs and CLI utility patterns to assist external research projects and AI agent workflows using the packaged KB.

Subphases:
- 11B: Implement dynamic cohort data dictionary generators querying the SQLite FTS5 backend.
- 11C: Implement a code caveat and limitation scanner to check analysis scripts against KB text chunks.
- 11D: Expose RAG-oriented context formatters for code generators and external agents.

Verification:
- Integration APIs run correctly on sample scripts and cohort columns.
- Helper queries resolve exact variable matches and return clean citation links.
- Context outputs match the existing `SearchResult` and Pydantic models.

### Phase 12: Evaluation Suite
Purpose: measure retrieval and agent-context quality with gold-standard CMS
research questions.

Subphases:
- 12A: Create benchmark questions with expected datasets, variables, source
  documents, and citation evidence.
- 12B: Add evaluation commands that report recall, MRR, and citation accuracy.
- 12C: Use evaluation results to compare lexical, hybrid, and agent-facing
  retrieval paths.

Verification:
- Evaluation fixtures are provenance-aware and do not require restricted CMS
  data.
- Evaluation commands run locally with `uv`.
- Results identify both answer recall and citation correctness.

### Phase 13: Source Expansion
Purpose: expand archived documentation beyond the current ResDAC source set
while preserving the archive-first provenance model.

Subphases:
- 13A: Add source-family configuration for related CMS and CCW documentation.
- 13B: Add TAF, VRDC, Medicare Advantage encounter, and Medicaid technical
  documentation sources as bounded inventory/archive targets.
- 13C: Update source coverage documentation with entry points, corpus counts,
  and source-family limitations.

Verification:
- New source families produce inventory and archive manifest rows with source
  URLs, checksums, timestamps, status, and local paths.
- Source expansion does not weaken existing ResDAC inventory, archive, or QA
  behavior.

### Phase 14: Research Workflow Assistance
Purpose: build higher-level grounded workflows only after source coverage,
retrieval quality, and evaluation are strong enough to support them.

Subphases:
- 14A: Add workflow-oriented query helpers for common CMS research discovery
  tasks such as enrollment, diagnoses, linkage, and data availability.
- 14B: Add structured response shapes for recommended datasets, variables,
  caveats, and supporting citations.
- 14C: Document boundaries so the system recommends documentation-backed data
  discovery paths, not research conclusions.

Verification:
- Workflow outputs cite archived documentation for every recommendation.
- Responses distinguish documented facts from inferred workflow suggestions.
- The system continues to avoid PHI, restricted CMS data, and unsupported
  research conclusions.
