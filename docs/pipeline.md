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
follows discovered dataset and documentation pages, records variable-detail
links from documentation tables, and probes linked assets.

For a bounded smoke test:

```bash
uv run cms-kb --max-listing-pages 1 --max-follow-pages 10 --max-assets 10 --request-delay-seconds 0.5
```

Outputs:

- `manifests/site_inventory.csv`
- `manifests/site_inventory_edges.csv`
- `_workspace/02_source_inventory.md`
- `_workspace/02_inventory_progress.jsonl` when progress logging is enabled (truncated per run)

Use `--no-progress-log` to disable file progress. Use `--progress-interval 0` to
disable periodic rollup lines while keeping per-row JSONL events.

If `_workspace/02_source_inventory.md` reports transient unresolved links,
rerun with a larger `--request-delay-seconds` before starting the archive pass.

## Phase 1: Archive Preservation

Phase 1 is intentionally split into two passes. ResDAC rate-limits bulk
variable-detail downloads, so a single full pass often archives datasets,
documentation, and assets successfully while deferring thousands of variable
pages after repeated HTTP 429 responses.

### Phase 1A: Initial archive pass

Archive the full inventory once. Expect non-variable rows to archive cleanly;
variable pages may end up `failed` (real 429s) or `deferred` (circuit breaker).

```bash
uv run cms-kb-archive --request-delay-seconds 1.0
```

Outputs:

- `data/raw/html/...`
- `data/raw/assets/...`
- `manifests/archive_manifest.csv`
- `_workspace/03_archive_manifest.md`
- `_workspace/03_archive_progress.jsonl` when progress logging is enabled (truncated per run)

Use `--progress-interval 25` (default) for periodic rollup events and stderr
status lines. Use `--no-progress-log` to disable file progress entirely.

Progress counters:

| Counter | Meaning |
| --- | --- |
| `archived` | Successfully stored with checksum |
| `failed` | Real download or validation errors |
| `deferred` | Skipped after the rate-limit circuit breaker (not a download failure) |
| `download_attempts` | Actual network requests in this run |

When the inventory contains more than 100 variable-page rows and no
`--max-downloads` cap is set, the archiver prints a pre-flight warning
recommending Phase 1B batches.

### Phase 1B: Bounded variable-page recovery

Retry failed and deferred variable pages in small batches. Repeat until
`_workspace/03_archive_manifest.md` shows `Deferred: 0` or you accept partial
variable-page coverage.

```bash
uv run cms-kb-archive \
  --retry-failed-only \
  --max-downloads 5000 \
  --request-delay-seconds 5 \
  --rate-limit-cooldown-seconds 300
```

Monitor long runs:

```bash
tail -f _workspace/03_archive_progress.jsonl
uv run cms-kb-progress _workspace/03_archive_progress.jsonl --lines 50
```

### Proceeding to Phase 2

Dataset, documentation, and asset rows should be `archived`. Variable-page gaps
are acceptable for extraction and QA; fill them iteratively with Phase 1B.

Standalone variable-detail pages may be rate-limited by ResDAC during large
archive refreshes. The archive pass retries `429 Too Many Requests` responses
politely, respects `Retry-After` when provided, and bulk-defers remaining
variable-page requests after repeated 429s. Failed and deferred variable-page
rows are retained in the manifest as explicit coverage gaps; dataset/document
extraction requires the dataset, documentation, and asset rows to remain
archived.

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
- `data/parsed/xlsx/...`
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
- `data/metadata/canonical_variables.csv`
- `data/graph/variable_edges.csv`
- `data/graph/data_source_variable_edges.csv`
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

Run a deterministic variable-retrieval usefulness smoke evaluation:

```bash
uv run cms-kb-evaluate-variables --sample-size 10 --seed 20260616 --json
```

The evaluation samples retained variable names, runs exact variable-name
retrieval, and reports whether matching variable results appear with useful
snippets and citation provenance.
