# SQLite FTS5 Retrieval Implementation Plan

## Task restatement

Replace per-query corpus-wide BM25 computation with a deterministic SQLite FTS5
serving index while preserving the existing retrieval and citation interfaces,
then extend the existing benchmark script into the evaluation gate for the new
backend.

## Current understanding

- `src/cms_kb/retrieval.py` validates and flattens canonical CSV/JSONL inputs
  into `RetrievableRecord` values.
- `search_records` currently computes token statistics and scores all records
  for every query.
- `SearchResult`, the CLI, agent context API, and MCP tools depend on stable
  result fields and citation provenance.
- `scripts/benchmark_retrieval.py` measures mean latency for five queries but
  does not yet test ranking quality or citation completeness.
- The SQLite database will be a derived artifact, not a canonical source.

## Assumptions

- The supported Python runtime exposes SQLite with FTS5 enabled.
- Rebuilding the complete index atomically is acceptable at the current corpus
  size; incremental index mutation is not required initially.
- Existing exact-match boosts and deterministic tie-breaking are behavior to
  preserve unless an evaluation fixture explicitly changes the expectation.
- Existing `SearchResult` fields and agent-facing interfaces must not change.

If an assumption is false, stop and report the mismatch before broadening the
implementation.

## Minimal implementation plan

1. Add an index path to `RetrievalConfig` and implement a deterministic builder
   that validates canonical inputs through `load_retrievable_records`, writes a
   temporary SQLite database, creates content/provenance tables and an FTS5
   table, verifies row counts, then atomically replaces the target index.
2. Configure FTS5 tokenization to preserve underscores. Index separate
   identifier, title, dataset ID, and body fields so BM25 field weights can
   prioritize structured metadata.
3. Implement parameterized SQLite query construction, BM25 scoring, explicit
   normalized exact-term boosts, deterministic tie-breaking, snippets, result
   filtering, and limits. Map rows back into the unchanged `SearchResult`
   model.
4. Keep `search_records` available as a temporary reference backend. Route
   `run_retrieval` and the CLI to SQLite only after an index exists and
   correctness tests pass; provide a clear missing/stale-index error rather
   than silently rebuilding during a query.
5. Extend `scripts/benchmark_retrieval.py` with CLI-configurable trials,
   fixtures, backend selection, offline-by-default execution, index-build/cold/
   warm timing, median and p95 statistics, ranked IDs, Recall@5, reciprocal
   rank, and citation completeness.
6. Add a small checked-in evaluation fixture containing exact identifier,
   acronym, phrase, conceptual, no-match, punctuation, and underscore-bearing
   queries with expected top results or required result sets.
7. Compare SQLite results with the reference backend, tune only documented
   field and exact-match weights, and record measured results in the performance
   report.
8. After the gate passes, make SQLite the default retrieval path and document
   the explicit index-build/rebuild command.

## Files and functions likely to change

- `src/cms_kb/retrieval.py`: configuration, index build/query functions, CLI
  routing, and unchanged result mapping.
- `pyproject.toml`: add an index-build CLI entry point only if the existing
  search CLI cannot cleanly expose a build subcommand; no database dependency
  is expected.
- `tests/test_retrieval.py`: index build, query semantics, exact boosts,
  deterministic ordering, missing index, snippets, and provenance tests.
- `tests/fixtures/` or a focused retrieval evaluation fixture: expected ranked
  results and citations.
- `scripts/benchmark_retrieval.py`: repeatable performance and quality
  evaluation harness.
- `README.md`, `docs/developer-guide.md`, and `docs/user-manual.md`: index build
  and query operation after behavior is implemented.
- `docs/retrieval_performance_report.md`: measured post-implementation results.
- `SPEC.md`, `ARCHITECTURE.md`, and `CHANGELOG.md`: feature-state, architecture,
  and release-history updates after verification.

Avoid editing files outside this list unless the plan conflicts with the actual
call graph. If it does, stop and explain the mismatch.

## Tests and checks

Run:

```bash
uv run pytest tests/test_retrieval.py tests/test_agent_api.py tests/test_mcp.py
uv run ruff check .
uv run basedpyright .
uv run python scripts/benchmark_retrieval.py --offline
```

Expected results:

- The index contains one searchable row per validated retrievable record.
- Exact identifier queries rank their expected record first.
- Phrase and conceptual fixtures satisfy their expected Recall@5 and reciprocal
  rank thresholds.
- Returned URLs, local source paths, pages, types, and IDs match source records.
- Repeated queries have deterministic ordering.
- Warm SQLite p95 latency is materially below the current 1.2693-second mean
  baseline; the initial target is below 10 milliseconds on the benchmark host.

Fix only failures caused by this work. Report unrelated failures separately.

## Acceptance criteria

- `data/index/retrieval.sqlite` can be rebuilt deterministically from canonical
  metadata and chunk inputs through a documented `uv run` command.
- Query execution does not tokenize or score the complete corpus in Python.
- Existing agent-facing result fields and citation behavior are unchanged.
- Exact underscore-bearing identifiers remain reliable top results.
- The evaluation command runs offline by default and emits machine-readable
  latency and retrieval-quality metrics.
- The checked-in regression fixture passes with no measured relevance or
  citation regression against the accepted baseline.
- Measured warm latency and index-build details replace projections in the
  performance report.

## Non-goals

- Do not add DuckDB, a vector database, embeddings, or semantic reranking.
- Do not replace canonical CSV/JSONL artifacts with SQLite.
- Do not add incremental indexing, background services, or schema migrations in
  the first implementation.
- Do not rename public result fields, MCP tools, or CLI query options.
- Do not preserve byte-for-byte score equality with the custom BM25 formula;
  preserve ranked behavior through explicit evaluation expectations.
- Do not perform unrelated retrieval, parsing, or documentation cleanup.

## Stop conditions

Stop and request review if:

- FTS5 is unavailable in a supported Python runtime.
- Preserving exact identifiers requires a native SQLite extension or custom
  tokenizer rather than built-in tokenizer configuration and explicit boosts.
- The implementation requires changing `SearchResult` or agent/MCP public
  response shapes.
- Atomic full-index rebuild is not acceptable for the generated corpus.
- More than the listed retrieval, evaluation, test, and documentation surfaces
  require semantic changes.
- The SQLite backend materially lowers accepted retrieval quality after bounded
  field-weight tuning.

## Review checklist

- The diff uses SQLite only as a rebuildable derived serving index.
- SQL and FTS queries are parameterized, and user query syntax is escaped or
  normalized deliberately.
- Underscore identifiers, phrases, empty input, punctuation-only input, and no
  matches have focused tests.
- Exact boosts and tie-breaking are explicit and deterministic.
- Citation provenance survives index build and result mapping unchanged.
- Benchmark timing separates build, cold, and warm paths and reports
  distributions rather than only means.
- Quality fixtures test ranked IDs and citations instead of overfitting to
  floating-point score values.
- Documentation states measured results and does not repeat an unverified
  latency claim.
- The implementation report lists files changed, tests run, deviations, and
  unresolved risks.

## Risk label

Risk: medium

Reason: the persistence and ranking implementation changes under several
existing callers, but the public result model remains stable and the old
backend provides a bounded regression reference.

Implementation handoff: Implement exactly this plan. Do not broaden scope. If
the plan conflicts with the codebase, stop and report the conflict instead of
improvising. Report files changed, tests run, deviations from the plan, and
unresolved risks.
