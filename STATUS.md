# Project Status

This repository has two independently tracked surfaces:

- Code: Python modules, CLIs, tests, and documentation for crawling,
  archiving, extraction, parsing, QA, variable extraction, and retrieval.
- Data: archived source documents, provenance manifests, and generated
  knowledge-base artifacts derived from those archives.

Keep these surfaces separate when reporting status. A pipeline capability can
be implemented even when its generated data artifacts are not checked in.

## Code Implementation Status

Status: implemented through the deterministic retrieval MVP.

The current Python implementation includes:

- Inventory discovery for ResDAC listing, dataset, documentation, and asset
  links.
- Archive preservation for raw HTML pages and linked assets with checksums.
- Metadata extraction for datasets, documents, ontology seeds, and graph edges.
- HTML/PDF parsing and provenance-bearing chunk generation.
- QA checks for checksums, source URLs, local paths, and cross-file references.
- Conservative variable-level metadata extraction from parsed chunks.
- Deterministic lexical retrieval across datasets, documents, variables, and
  parsed chunks.
- Minimal agent-facing context retrieval that returns citation-preserving JSON
  and Pydantic models.

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

Status: derived outputs are pipeline products, but the current checked-in data
snapshot does not include them.

The pipeline can generate these artifacts:

- `data/metadata/datasets.csv`
- `data/metadata/documents.csv`
- `data/metadata/variables.csv`
- `data/graph/document_edges.csv`
- `data/graph/ontology_nodes.csv`
- `data/graph/ontology_edges.csv`
- `data/graph/variable_edges.csv`
- `data/parsed/html/...`
- `data/parsed/pdf/...`
- `data/parsed/chunks/...`
- `data/parsed/chunks.jsonl`

Agent context results are generated on demand from the retrieval inputs and are
not retained as derived artifacts.

When these files are generated and intentionally retained, update this file
with the artifact paths, row counts or file counts, and the command used to
produce them.

## Update Rules

- Update `SPEC.md` when implementation work moves between future, active, and
  completed states.
- Update this file when checked-in corpus coverage or retained generated
  artifacts change.
- Update `docs/source-coverage.md` when source families, entry points, or
  archive scope change.
- Do not describe generated artifacts as present unless they exist in the
  repository or are explicitly documented as local-only outputs.
