# Data Model Guide

The knowledge base stores provenance-bearing records derived from archived
public CMS documentation. Every derived record should retain enough source
context to trace it back to the archived document or source URL.

## Dataset

Dataset records describe CMS data products extracted from archived dataset
pages.

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

Primary output:

- `data/metadata/datasets.csv`

## Document

Document records describe documentation pages and assets associated with
datasets.

```json
{
  "document_id": "...",
  "title": "...",
  "url": "...",
  "content_type": "...",
  "local_path": "..."
}
```

Primary output:

- `data/metadata/documents.csv`

## Variable

Variable records describe conservative variable-level evidence extracted from
parsed chunks.

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

Primary output:

- `data/metadata/variables.csv`

## Canonical Variable

Canonical variable records describe standalone ResDAC variable-detail pages when
they are archived. They use the variable-detail URL slug as the canonical
identity so one semantic variable can connect to many data sources.

```json
{
  "variable_id": "...",
  "variable_name": "...",
  "variable_label": "...",
  "definition": "...",
  "source_url": "...",
  "source_document": "..."
}
```

Primary output:

- `data/metadata/canonical_variables.csv`

## Graph Seeds

The graph outputs represent lightweight relationships among datasets,
documents, programs, categories, availability values, and variables.

Example relationship shapes:

```text
Dataset -> contains -> Variable
Dataset -> contains -> CanonicalVariable
Dataset -> belongs_to -> Program
Dataset -> related_to -> Dataset
Dataset -> documented_by -> Document
```

Primary outputs:

- `data/graph/document_edges.csv`
- `data/graph/ontology_nodes.csv`
- `data/graph/ontology_edges.csv`
- `data/graph/variable_edges.csv`
- `data/graph/data_source_variable_edges.csv`

## Parsed Chunks

Parsed chunks provide text retrieval units with document, dataset, URL, page,
and chunk provenance when available.

Primary outputs:

- `data/parsed/html/...`
- `data/parsed/pdf/...`
- `data/parsed/chunks/...`
- `data/parsed/chunks.jsonl`

## Provenance Expectations

Derived records should preserve:

- Source URL.
- Local archived path when available.
- Source document identifier when available.
- Page or chunk identifier when available.
- Checksum lineage through manifests for archived files.

Retrieval results should include citations back to source URLs and local source
document/page provenance when available. Agent context citations can also
include variable-detail URLs. The local variable-detail document is populated
only when that standalone variable page is archived locally.
