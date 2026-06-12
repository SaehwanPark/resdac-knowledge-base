# SPEC

## Past
- Initial canonical documentation bootstrap completed.

## Present
- Phase 0 inventory discovery is implemented and writes machine-readable and workspace inventory outputs.
- Phase 1 archive preservation is implemented and writes raw HTML/assets plus an archive manifest and workspace summary.
- Phase 2 metadata extraction is implemented for archived dataset pages, documentation pages, and assets, with checksum validation and provenance-bearing CSV outputs.
- Phase 3 document parsing is implemented, parsing text from HTML/PDFs and generating text chunks with preserved provenance.
- Phase 4 QA Specialist is implemented, performing checksum and url checks to audit provenance, reporting to _workspace/06_qa_review.md.
- Phase 5 CMS Research Ontology is implemented, normalizing program, category, and availability fields from HTML, and extracting graph node and edge seeds (belongs_to, related_to) with QA validation.
- Phase 6 variable-level metadata extraction is implemented, deriving conservative variable records from parsed chunks and writing provenance-bearing variable metadata and graph edges.

## Future
- Preserve ResDAC and related CMS documentation sources into canonical raw archives.
- Build retrieval and citation-backed agent support on top of the archived corpus.
