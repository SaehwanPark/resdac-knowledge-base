# Pipeline Guide

This guide lists the local pipeline commands, their purpose, and the primary
artifacts they produce. Run Python commands through `uv`.

## Development Checks

```bash
uv sync
uv run pytest
uv run ruff check .
uv run basedpyright .
uv run python scripts/validate_harness.py
```

## Phase 0: Inventory

Run the inventory crawl against ResDAC listing pages:

```bash
uv run cms-kb --max-listing-pages 10 --request-delay-seconds 1.0
```

`--max-pages` and `--max-listing-pages` limit ResDAC listing pages only. Use a
ceiling higher than the currently known listing count; the crawler stops when a
later listing page repeats or contains no discovered links. The crawler also
follows discovered dataset and documentation pages and probes linked assets.

For a bounded smoke test:

```bash
uv run cms-kb --max-listing-pages 1 --max-follow-pages 10 --max-assets 10 --request-delay-seconds 0.5
```

Outputs:

- `manifests/site_inventory.csv`
- `_workspace/02_source_inventory.md`

If `_workspace/02_source_inventory.md` reports transient unresolved links,
rerun with a larger `--request-delay-seconds` before starting the archive pass.

## Phase 1: Archive Preservation

Run the archive pass against the inventory output:

```bash
uv run cms-kb-archive --request-delay-seconds 0.5
```

Outputs:

- `data/raw/html/...`
- `data/raw/assets/...`
- `manifests/archive_manifest.csv`
- `_workspace/03_archive_manifest.md`

## Phase 2: Metadata Extraction

Run metadata extraction against the archive manifest:

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

## Phase 3: Document Parsing

Run parsing against extracted metadata:

```bash
uv run cms-kb-parse
```

Outputs:

- `data/parsed/html/...`
- `data/parsed/pdf/...`
- `data/parsed/chunks/...`
- `data/parsed/chunks.jsonl`
- `_workspace/05_parsing_pack.md`

## Phase 4: QA

Run QA after extraction, parsing, or variable updates:

```bash
uv run cms-kb-qa
```

Output:

- `_workspace/06_qa_review.md`

## Phase 6: Variable Metadata

Run variable metadata extraction against parsed chunks:

```bash
uv run cms-kb-variables
```

Outputs:

- `data/metadata/variables.csv`
- `data/graph/variable_edges.csv`
- `_workspace/07_variable_pack.md`

## Phase 7: Retrieval MVP

Run deterministic local lexical search over metadata and parsed chunks:

```bash
uv run cms-kb-search --query BENE_ID --limit 5 --json
```

Results include stable IDs, snippets, scores, and source citations.

Return the same retrieval evidence as JSON context for agent workflows:

```bash
uv run cms-kb-agent-context --query BENE_ID --limit 5 --json
```

The context response nests source URL, local source document, and page
provenance under each result citation.
