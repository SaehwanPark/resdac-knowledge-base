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

## Present
- No active implementation item is currently tracked.

## Future
- Expand archived documentation beyond the current ResDAC source set to related CMS, CCW, TAF, VRDC, Medicare Advantage encounter, and Medicaid technical documentation sources.
- Add richer agent integrations or tools on top of the archived corpus, metadata catalog, graph seeds, variable records, retrieval layer, and minimal context API.
- Add hybrid retrieval beyond the deterministic lexical MVP, including optional semantic retrieval or reranking while preserving source citations.
- Add benchmark evaluation with gold-standard CMS research questions, expected datasets or variables, and citation accuracy checks.
