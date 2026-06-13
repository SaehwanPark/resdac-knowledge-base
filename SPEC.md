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
- Minimal agent-facing context API is implemented, exposing retrieval results as citation-preserving Pydantic models and JSON CLI output.
- Documentation state model clarified so Past, Present, and Future are mutually exclusive and completed phases no longer appear as active work.
- Phase 8: MCP Agent Integration is implemented, exposing read-only MCP server and tools (search_datasets, search_documents, search_variables, search_chunks, get_agent_context) over the retrieval API.
- Comprehensive end-user manual ([user-manual.md](file:///Users/saehwan/repos/resdac-knowledge-base/docs/user-manual.md)) and developer guide ([developer-guide.md](file:///Users/saehwan/repos/resdac-knowledge-base/docs/developer-guide.md)) created and linked to README.md.

## Present
- No active implementation item is currently tracked.

## Future
Future work is organized as implementation phases. A phase may be promoted into
`Present` when active work begins, with concise verification criteria and
explicit out-of-scope notes.

### Phase 9: Source Expansion
Purpose: expand archived documentation beyond the current ResDAC source set
while preserving the archive-first provenance model.

Subphases:
- 9A: Add source-family configuration for related CMS and CCW documentation.
- 9B: Add TAF, VRDC, Medicare Advantage encounter, and Medicaid technical
  documentation sources as bounded inventory/archive targets.
- 9C: Update source coverage documentation with entry points, corpus counts,
  and source-family limitations.

Verification:
- New source families produce inventory and archive manifest rows with source
  URLs, checksums, timestamps, status, and local paths.
- Source expansion does not weaken existing ResDAC inventory, archive, or QA
  behavior.

### Phase 10: Hybrid Retrieval And Ranking
Purpose: improve retrieval quality beyond the deterministic lexical MVP while
keeping exact matching and citations as first-class behavior.

Subphases:
- 10A: Add benchmarkable lexical ranking improvements for CMS identifiers,
  aliases, acronyms, and phrase queries.
- 10B: Add optional semantic retrieval or reranking behind explicit
  configuration.
- 10C: Preserve deterministic citation output and make ranking changes
  measurable against evaluation questions.

Verification:
- Retrieval results still include source citations for every returned record.
- Exact identifier queries such as `BENE_ID`, `MSIS_ID`, `CLM_ID`, and `PDE_ID`
  remain reliable.
- Optional semantic or reranking behavior can be disabled for deterministic
  local runs.

### Phase 11: Evaluation Suite
Purpose: measure retrieval and agent-context quality with gold-standard CMS
research questions.

Subphases:
- 11A: Create benchmark questions with expected datasets, variables, source
  documents, and citation evidence.
- 11B: Add evaluation commands that report recall, MRR, and citation accuracy.
- 11C: Use evaluation results to compare lexical, hybrid, and agent-facing
  retrieval paths.

Verification:
- Evaluation fixtures are provenance-aware and do not require restricted CMS
  data.
- Evaluation commands run locally with `uv`.
- Results identify both answer recall and citation correctness.

### Phase 12: Research Workflow Assistance
Purpose: build higher-level grounded workflows only after source coverage,
retrieval quality, and evaluation are strong enough to support them.

Subphases:
- 12A: Add workflow-oriented query helpers for common CMS research discovery
  tasks such as enrollment, diagnoses, linkage, and data availability.
- 12B: Add structured response shapes for recommended datasets, variables,
  caveats, and supporting citations.
- 12C: Document boundaries so the system recommends documentation-backed data
  discovery paths, not research conclusions.

Verification:
- Workflow outputs cite archived documentation for every recommendation.
- Responses distinguish documented facts from inferred workflow suggestions.
- The system continues to avoid PHI, restricted CMS data, and unsupported
  research conclusions.
