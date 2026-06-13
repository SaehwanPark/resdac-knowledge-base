# Project Status

This repository has two independently tracked surfaces:

- Code: Python modules, CLIs, tests, and documentation for crawling,
  archiving, extraction, parsing, QA, variable extraction, and retrieval.
- Data: archived source documents, provenance manifests, and generated
  knowledge-base artifacts derived from those archives.

Keep these surfaces separate when reporting status. A pipeline capability can
be implemented even when its generated data artifacts are not checked in.

## Code Implementation Status

Status: implemented through the MCP Agent Integration.

The current Python implementation includes:

- Inventory discovery for ResDAC listing, dataset, documentation, and asset
  links.
- Archive preservation for raw HTML pages and linked assets with checksums.
- Metadata extraction for datasets, documents, ontology seeds, and graph edges.
- HTML/PDF/XLSX parsing and provenance-bearing chunk generation.
- QA checks for checksums, source URLs, local paths, and cross-file references.
- Conservative variable-level metadata extraction from parsed chunks.
- Deterministic lexical retrieval across datasets, documents, variables, and
  parsed chunks.
- Minimal agent-facing context retrieval that returns citation-preserving JSON
  and Pydantic models.
- Read-only Model Context Protocol (MCP) server for integration with AI agents.

`SPEC.md` tracks implementation lifecycle state with mutually exclusive
`Past`, `Present`, and `Future` sections.

## Data Corpus Status

Status: raw ResDAC archive snapshot is checked in.

The checked-in corpus currently includes:

- `manifests/site_inventory.csv`: 339 inventory rows.
- `manifests/archive_manifest.csv`: 339 archive provenance rows.
- `data/raw/html/listing_page/`: 5 archived listing pages.
- `data/raw/html/dataset_page/`: 154 archived dataset pages.
- `data/raw/html/documentation_page/`: 93 archived documentation pages.
- `data/raw/assets/pdf/`: 36 archived PDF assets.
- `data/raw/assets/xlsx/`: 50 archived XLSX assets.

This snapshot is source material for downstream extraction and retrieval.

## Derived Artifact Status

Status: derived outputs are generated and retained from the checked-in ResDAC
archive snapshot.

The retained generated artifacts are:

- `data/metadata/datasets.csv`: 96 dataset rows.
- `data/metadata/documents.csv`: 179 document rows.
- `data/metadata/variables.csv`: 153 variable rows.
- `data/graph/document_edges.csv`: 179 document edge rows.
- `data/graph/ontology_nodes.csv`: 99 ontology node rows.
- `data/graph/ontology_edges.csv`: 253 ontology edge rows.
- `data/graph/variable_edges.csv`: 153 variable edge rows.
- `data/parsed/html/`: 189 parsed HTML text files.
- `data/parsed/pdf/`: 36 parsed PDF text files.
- `data/parsed/xlsx/`: 50 parsed XLSX text files.
- `data/parsed/chunks/`: 27,123 per-chunk JSON files.
- `data/parsed/chunks.jsonl`: 27,123 chunk rows.

Agent context results are generated on demand from the retrieval inputs and are
not retained as derived artifacts.

These retained artifacts were produced by `uv run cms-kb-extract`,
`uv run cms-kb-parse`, and `uv run cms-kb-variables`, then validated with
`uv run cms-kb-qa`.

## Retained KB Rebuild Run

Run started: 2026-06-12 18:50:16 EDT

Scope:

- Branch: `feat/build-retained-kb-artifacts`
- Source corpus: checked-in ResDAC archive snapshot.
- Live network use: bounded Phase 0/1 smoke test only, using temporary paths.
- Retention policy: retain generated metadata, graph, parsed, and workspace
  handoff artifacts when validation passes.

Completed steps:

- Request handoff recorded in `_workspace/01_request.md`.
- Preflight checks passed:
  - `uv sync`
  - `uv run pytest` — 73 passed, 5 warnings from PyMuPDF/SWIG imports.
  - `uv run ruff check .`
  - `uv run basedpyright .`
  - `uv run python scripts/validate_harness.py`
- Phase 0 live inventory smoke passed:
  - Command wrote 58 inventory rows to `/tmp/resdac-kb-smoke/site_inventory.csv`.
  - Handoff written to `/tmp/resdac-kb-smoke/_workspace/02_source_inventory.md`.
  - Checked-in `manifests/site_inventory.csv` was not replaced.
- Phase 1 live archive smoke passed:
  - Command wrote 58 archive rows to `/tmp/resdac-kb-smoke/archive_manifest.csv`.
  - Handoff written to `/tmp/resdac-kb-smoke/_workspace/03_archive_manifest.md`.
  - Checked-in `manifests/archive_manifest.csv` and `data/raw/` were not
    replaced.
- Phase 2 metadata extraction passed:
  - Initial extraction exposed two listing-sourced PDF assets that were linked
    from dataset pages but not resolved to datasets through manifest
    `source_url`.
  - Added focused extraction coverage, fixed asset-to-dataset resolution from
    archived dataset-page links, and filtered false ontology `related_to` edges
    from non-ResDAC dataset asset paths.
  - `uv run pytest tests/test_extraction.py` — 9 passed, 5 warnings from
    PyMuPDF/SWIG imports.
  - `uv run cms-kb-extract` wrote 96 datasets, 179 documents, 179 document
    edges, 99 ontology nodes, and 253 ontology edges.
  - Retained outputs: `data/metadata/datasets.csv`,
    `data/metadata/documents.csv`, `data/graph/document_edges.csv`,
    `data/graph/ontology_nodes.csv`, `data/graph/ontology_edges.csv`, and
    `_workspace/04_extraction_pack.md`.
- Phase 3 document parsing passed:
  - Initial parsing exposed 50 XLSX assets as unsupported document kinds.
  - Added dependency-free XLSX text extraction from workbook XML and focused
    parsing coverage.
  - `uv run pytest tests/test_parsing.py` — 11 passed, 5 warnings from
    PyMuPDF/SWIG imports.
  - `uv run cms-kb-parse` wrote 96 parsed datasets, 179 parsed documents, and
    27,123 chunks with zero failures.
  - Retained parsed text files: 189 HTML, 36 PDF, and 50 XLSX files.
  - Retained chunk outputs: 27,123 per-chunk JSON files and 27,123 JSONL rows
    in `data/parsed/chunks.jsonl`.
  - Documentation updated for `data/parsed/xlsx/`.
- Phase 6 variable metadata extraction passed:
  - `uv run cms-kb-variables` read 27,123 chunks.
  - Retained outputs: 153 variables in `data/metadata/variables.csv`, 153
    variable edges in `data/graph/variable_edges.csv`, and
    `_workspace/07_variable_pack.md`.
  - The variable extractor skipped 51,946 candidates and reported zero
    failures.
- Phase 4 QA passed:
  - `uv run cms-kb-qa` checked 96 datasets, 179 documents, 153 variables, and
    585 edges.
  - Verdict: PASS with 0 errors and 1 warning.
  - Remaining warning: one ontology `related_to` target, `mbsf`, does not map
    to a retained dataset, document, or ontology node.
  - Handoff written to `_workspace/06_qa_review.md`.
- Retrieval smoke checks passed:
  - `uv run cms-kb-search --query BENE_ID --limit 5 --json` returned five
    variable results with source URL, local source document, and page
    provenance.
  - `uv run cms-kb-agent-context --query BENE_ID --limit 5 --json` returned
    the same citation-preserving evidence nested under `citation`.
- Final validation passed:
  - `uv run pytest` — 75 passed, 5 warnings from PyMuPDF/SWIG imports.
  - `uv run ruff check .`
  - `uv run basedpyright .`
  - `uv run python scripts/validate_harness.py`
  - `uv run cms-kb-qa` — PASS with 0 errors and 1 warning.

## Update Rules

- Update `SPEC.md` when implementation work moves between future, active, and
  completed states.
- Update this file when checked-in corpus coverage or retained generated
  artifacts change.
- Update `docs/source-coverage.md` when source families, entry points, or
  archive scope change.
- Do not describe generated artifacts as present unless they exist in the
  repository or are explicitly documented as local-only outputs.
