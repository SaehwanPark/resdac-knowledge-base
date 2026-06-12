# CMS Documentation Knowledge Base

A reproducible archive, metadata catalog, and retrieval system for CMS (Medicare and Medicaid) data documentation.

## Motivation

CMS health policy research depends heavily on documentation distributed across ResDAC, CMS technical documentation, data dictionaries, user guides, and related resources.

These materials contain critical information regarding:

* Dataset availability
* Variable definitions
* Data linkage strategies
* Population coverage
* File relationships
* Known limitations and caveats
* Year-specific changes

As documentation sources evolve or become unavailable, research reproducibility and AI-assisted workflows become increasingly vulnerable.

This project aims to create a durable, locally maintained knowledge base that preserves documentation and transforms it into a structured, searchable resource suitable for both human researchers and AI agents.

## Objectives

### Preservation

Create a complete offline archive of publicly accessible CMS documentation resources.

### Knowledge Extraction

Transform unstructured documentation into structured metadata.

### Retrieval

Enable accurate retrieval of datasets, variables, concepts, and methodological guidance.

### Agent Support

Provide AI agents with grounded, citation-backed access to CMS data knowledge.

## Project Scope

### Phase 1: Documentation Preservation

Archive:

* HTML pages
* PDFs
* XLSX files
* CSV files
* Images and attachments

Primary initial target:

* ResDAC CMS Data pages

Potential future sources:

* CMS documentation
* CCW documentation
* TAF technical specifications
* VRDC resources
* Medicare Advantage encounter documentation
* Medicaid technical documentation

### Phase 2: Metadata Catalog

Extract structured information including:

* Dataset names
* Program affiliations
* Data availability
* Documentation links
* Special considerations
* Related files

### Phase 3: Knowledge Graph

Represent relationships among:

* Datasets
* Tables
* Variables
* Programs
* Concepts
* Documentation resources

Example:

Dataset -> contains -> Variable

Dataset -> belongs_to -> Program

Dataset -> related_to -> Dataset

Variable -> appears_in -> Dataset

### Phase 4: Retrieval Layer

Support:

* Exact matching
* Keyword retrieval
* Semantic retrieval
* Graph-based traversal

### Phase 5: AI Agent Integration

Provide APIs enabling agents to answer questions such as:

* Which files contain Medicare Advantage encounters?
* How can dual eligibility be identified?
* Which datasets contain beneficiary enrollment information?
* What are the limitations of TAF OT data?

All responses should include source citations.

## Architecture

```text
                   +------------------+
                   | Source Websites  |
                   +------------------+
                             |
                             v
                   +------------------+
                   |     Archiver     |
                   +------------------+
                             |
                             v
                   +------------------+
                   |  Raw Documents   |
                   +------------------+
                             |
                             v
                   +------------------+
                   | Metadata Parser  |
                   +------------------+
                             |
                             v
                   +------------------+
                   | Knowledge Store  |
                   +------------------+
                             |
                 +-----------+-----------+
                 |                       |
                 v                       v
        +----------------+     +----------------+
        | Search Indexes |     | Knowledge Graph|
        +----------------+     +----------------+
                 |                       |
                 +-----------+-----------+
                             |
                             v
                   +------------------+
                   | Retrieval API    |
                   +------------------+
                             |
                             v
                   +------------------+
                   | AI Agents        |
                   +------------------+
```

## Repository Structure

```text
resdac-knowledge-base/

├── data/
│   ├── raw/
│   ├── parsed/
│   ├── metadata/
│   └── graph/
│
├── manifests/
│
├── src/
│   └── cms_kb/
│
├── tests/
│
├── docs/
│   └── harness/cms-kb/
│
└── .agents/skills/
```

## Development

Use `uv` for dependency management and command execution.

```bash
uv sync
uv run pytest
uv run ruff check .
uv run basedpyright .
uv run python scripts/validate_harness.py
```

Run the Phase 0 inventory crawl against ResDAC:

```bash
uv run cms-kb --max-pages 4 --request-delay-seconds 0.5
```

`--max-pages`/`--max-listing-pages` limits ResDAC listing pages only. The
crawler also follows discovered dataset/documentation pages and probes linked
assets. For a bounded smoke test, add explicit follow-up limits:

```bash
uv run cms-kb --max-listing-pages 1 --max-follow-pages 10 --max-assets 10 --request-delay-seconds 0.5
```

Outputs:

- `manifests/site_inventory.csv`
- `_workspace/02_source_inventory.md`

Run the Phase 1 archive pass against the inventory output:

```bash
uv run cms-kb-archive --request-delay-seconds 0.5
```

Outputs:

- `data/raw/html/...`
- `data/raw/assets/...`
- `manifests/archive_manifest.csv`
- `_workspace/03_archive_manifest.md`

Run the Phase 2 metadata extraction pass against the archive manifest:

```bash
uv run cms-kb-extract
```

Outputs:

- `data/metadata/datasets.csv`
- `data/metadata/documents.csv`
- `data/graph/document_edges.csv`
- `data/graph/ontology_nodes.csv`
- `data/graph/ontology_edges.csv`
- `_workspace/04_extraction_pack.md`

Run the Phase 3 parsing pass against extracted metadata:

```bash
uv run cms-kb-parse
```

Outputs:

- `data/parsed/html/...`
- `data/parsed/pdf/...`
- `data/parsed/chunks/...`
- `data/parsed/chunks.jsonl`
- `_workspace/05_parsing_pack.md`

Run the Phase 6 variable metadata pass against parsed chunks:

```bash
uv run cms-kb-variables
```

Outputs:

- `data/metadata/variables.csv`
- `data/graph/variable_edges.csv`
- `_workspace/07_variable_pack.md`

Run the retrieval MVP against metadata and parsed chunks:

```bash
uv run cms-kb-search --query BENE_ID --limit 5 --json
```

The retrieval layer performs local lexical search over datasets, documents,
variables, and chunks. Results include stable IDs, snippets, scores, and
source citations.

Run the QA Specialist after extraction, parsing, or variable updates:

```bash
uv run cms-kb-qa
```

Output:

- `_workspace/06_qa_review.md`

## Core Data Model

### Dataset

```json
{
  "dataset_id": "...",
  "name": "...",
  "program": "...",
  "description": "...",
  "availability": "...",
  "source_url": "..."
}
```

### Variable

```json
{
  "variable_id": "...",
  "variable_name": "...",
  "dataset_id": "...",
  "definition": "...",
  "aliases": "...",
  "years": "...",
  "source_document": "...",
  "source_url": "...",
  "chunk_id": "..."
}
```

### Document

```json
{
  "document_id": "...",
  "title": "...",
  "url": "...",
  "content_type": "...",
  "local_path": "..."
}
```

## Development Roadmap

`SPEC.md` is the operational source of truth for whether work is Past,
Present, or Future. The milestones below summarize the strategic direction and
may include both completed and planned layers.

### Milestone 1

Documentation inventory and archival pipeline.

### Milestone 2

Structured metadata extraction.

### Milestone 3

Document parsing and chunk generation.

### Milestone 4

Knowledge graph construction.

### Milestone 5

Retrieval system, starting with deterministic lexical search and preserving
future room for hybrid or semantic retrieval.

### Milestone 6

Agent-facing APIs.

### Milestone 7

Benchmark evaluation suite.

## Guiding Principles

### Preserve First

Never discard source documents.

### Provenance Everywhere

Every extracted fact must retain a traceable source.

### Structure Over Embeddings

Prefer explicit metadata and relationships whenever possible.

### Reproducibility

All artifacts should be rebuildable from source inputs.

### Agent-Friendly Design

Expose information through stable, structured interfaces rather than relying solely on document retrieval.

## Long-Term Vision

Create an institutional knowledge base for CMS data research that enables both human researchers and AI agents to reliably discover:

* Appropriate datasets
* Relevant variables
* Methodological caveats
* Data linkage strategies
* Documentation sources

while maintaining transparent provenance and reproducibility.

## Non-Goals

This project is not intended to:

- Host CMS restricted data
- Store PHI
- Replicate CMS analytical datasets
- Generate research conclusions

The project only manages metadata, documentation,
knowledge representations, and retrieval infrastructure.

## ResDAC Data Files' Entry Points

- https://resdac.org/cms-data?page=0
- https://resdac.org/cms-data?page=1
- https://resdac.org/cms-data?page=2
- https://resdac.org/cms-data?page=3
