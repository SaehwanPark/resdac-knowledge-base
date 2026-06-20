# ResDAC Search Retrieval Performance Report

This report records the initial retrieval benchmark, identifies the current
local-search bottleneck, and defines the next retrieval implementation target.
All approaches return the same minimal result shape so serialization work is
included in their measured latency:

```json
{
  "title": "<Result Title>",
  "url": "<Canonical Source URL>",
  "snippet": "<Query-Centric Text Snippet>"
}
```

Equal output shape does not make the approaches equivalent retrieval systems.
They use different corpora, matching semantics, ranking behavior, caching, and
network boundaries. The results are therefore useful as a baseline, not as a
strictly controlled comparison of retrieval quality.

## 1. Experimental Setup

The benchmark used five representative query profiles:

- `BENE_ID`: exact CMS variable identifier.
- `medicare advantage`: multi-term program phrase.
- `dual eligibility`: health-policy concept.
- `MBSF`: dataset acronym.
- `encounter`: common domain term.

Each query was run for three trials and the arithmetic mean was reported. The
small query set and trial count are adequate for detecting the current
order-of-magnitude bottleneck, but not for setting a production latency service
level or making statistically strong performance claims.

The compared approaches were:

1. **Internet search:** request the live ResDAC Drupal search page, parse its
   HTML, and return the first five results.
2. **Local raw-data grep:** recursively scan archived HTML, parse the first five
   matching files, and resolve canonical URLs through
   `manifests/archive_manifest.csv`.
3. **Current local KB search:** use the custom BM25 implementation in
   [`retrieval.py`](../src/cms_kb/retrieval.py), either through a cold CLI
   subprocess or against records already loaded into a Python process.

The experiment is implemented in
[`benchmark_retrieval.py`](../scripts/benchmark_retrieval.py). Its original
output is retained in `_workspace/benchmark_results.json` when generated
locally.

## 2. Baseline Results

Mean retrieval latency in seconds from the 2026-06-20 run:

| Query | Internet | Local grep | Current KB cold CLI | Current KB warm |
| :--- | ---: | ---: | ---: | ---: |
| `BENE_ID` | 0.1286 | 2.6681 | 2.3181 | 1.2207 |
| `medicare advantage` | 0.1374 | 2.9931 | 2.4500 | 1.3529 |
| `dual eligibility` | 0.1320 | 2.9206 | 2.3996 | 1.2736 |
| `MBSF` | 0.1600 | 2.7322 | 2.4015 | 1.2501 |
| `encounter` | 0.1364 | 3.3121 | 2.3694 | 1.2492 |
| **Mean** | **0.1389** | **2.9252** | **2.3877** | **1.2693** |

## 3. Interpretation

### Internet search

The live endpoint was fastest in this run, but it is not a suitable agent
retrieval dependency. It is network-dependent, subject to HTTP 429 responses,
and cannot guarantee availability or stable ranking. It also searches the live
site rather than the preserved local corpus.

### Local raw-data grep

Grep scans thousands of archived files for every query and provides no
relevance ranking. Filesystem ordering determines which matches are processed
first. It remains useful for diagnostics, but not as an agent-facing retrieval
path.

### Current local KB search

The current implementation provides the strongest behavior: deterministic
offline retrieval, BM25-style scoring, exact identifier and title boosts, and
citation-bearing results. Its latency comes from recomputing corpus statistics
and term frequencies for every query:

- `_idf_by_token` tokenizes every record and rebuilds document frequencies.
- `search_records` recomputes every document length.
- `_record_score` retokenizes and recounts every candidate record.
- Every record is scored even when it contains none of the query terms.

Warm loading is not the primary bottleneck. Building an inverted index once and
querying only matching postings is the required optimization.

## 4. Storage and Search Decision

Use **SQLite FTS5** as a derived, rebuildable serving index. Do not adopt
DuckDB for retrieval and do not build a custom JSON inverted-index format.

SQLite FTS5 supplies the required inverted index, BM25 ranking, field weights,
phrase and prefix queries, and query-centric snippets. It is accessible through
Python's standard `sqlite3` module and can package searchable content,
provenance fields, and index data in one portable file.

The index is a derived artifact. CSV and JSONL metadata remain canonical inputs,
and the SQLite database must be reproducible from them:

```text
data/metadata/*.csv + data/parsed/chunks.jsonl
                         |
                         v
              data/index/retrieval.sqlite
                         |
                         v
             existing SearchResult interface
```

The searchable schema should separate at least these logical fields:

```text
identifier | title | dataset_id | body
```

FTS5 BM25 field weights should favor identifiers and titles. Explicit
case-normalized equality boosts must remain outside the BM25 score so exact CMS
identifiers such as `BENE_ID` reliably outrank incidental text matches. The
tokenizer must preserve underscores, and query construction must preserve the
current multi-term matching behavior unless evaluation demonstrates an
intentional improvement.

No fixed latency claim is made before implementation. Sub-10-millisecond warm
search is a reasonable benchmark target for the current corpus, but it is an
acceptance target to measure rather than an assumed result.

## 5. Immediate Implementation Target

The implementation queue and detailed acceptance criteria are defined in
[`sqlite-retrieval-plan.md`](sqlite-retrieval-plan.md). The immediate sequence
is:

1. Add a deterministic SQLite FTS5 index builder from validated
   `RetrievableRecord` values.
2. Add a SQLite-backed query path that preserves `SearchResult`, citation,
   snippet, exact-match boost, filtering, ordering, and limit behavior.
3. Keep the current in-memory implementation temporarily as a reference
   backend for regression comparison.
4. Convert `scripts/benchmark_retrieval.py` into a repeatable local evaluation
   tool that compares both local backends, records latency distributions, and
   checks ranked-result and citation expectations.
5. Make the SQLite backend the default only after correctness tests and the
   evaluation gate pass.

## 6. Evaluation Requirements

The existing benchmark script should be retained, but timing alone is
insufficient. Its next version should:

- accept query fixtures and trial count through CLI arguments;
- benchmark index build, cold query, and warm query separately;
- report median and p95 latency in addition to mean;
- record ranked result IDs, result types, and citation fields;
- support expected-result fixtures for exact identifier and phrase queries;
- calculate at least Recall@5, reciprocal rank, and citation completeness;
- keep internet and grep comparisons optional so the default evaluation is
  deterministic, offline, and safe from rate limits;
- write machine-readable JSON under `_workspace/` without treating generated
  benchmark output as a canonical source artifact.

The first regression set must include `BENE_ID`, `MSIS_ID`, `CLM_ID`, `PDE_ID`,
`MBSF`, `medicare advantage`, `dual eligibility`, and `encounter`. The SQLite
backend is acceptable when exact identifiers retain expected top-ranked
results, every result preserves its citation fields, and local warm-query
latency improves materially over this baseline without a measured relevance
regression.
