# LESSONS

Use this file to record recurring setup traps, debugging lessons, and workflow gotchas that would otherwise be easy to repeat.

## Entry Format

- Context: what task or area exposed the issue.
- Symptom: what failed or was confusing.
- Cause: the underlying reason.
- Resolution: what fixed it.
- Prevention: what future contributors should do first.

## Lessons

### Live inventory smoke test against ResDAC

- Context: first live inventory smoke test against `https://resdac.org/cms-data`.
- Symptom: `python` was not on PATH in the repo shell and the first site probes were rate-limited with HTTP 429.
- Cause: the environment expects `uv run python`, and ResDAC briefly throttled rapid repeated requests.
- Resolution: use `uv run python`/`uv run ...` for repo commands and add polite crawl delays plus retry handling for 429/503 responses.
- Prevention: check `which python3`/`which uv` before assuming a `python` entrypoint, and keep live inventory requests throttled.

### Ruff lint-only with 2-space indentation

- Context: switching back to lint-only Ruff usage for Python style checks.
- Symptom: `ruff format` conflicted with the repo's 2-space indentation requirement.
- Cause: Ruff's formatter is designed around 4-space Python indentation, while this repo keeps Python files at 2 spaces.
- Resolution: remove formatter usage, keep Ruff in lint-only mode, and reindent Python sources manually to 2 spaces.
- Prevention: keep Ruff in lint-only mode for this repo, and verify Python indentation directly when making style changes.

### Phase 0 crawl limits are split by resource type

- Context: running `uv run cms-kb --max-pages 4 --request-delay-seconds 0.5` as a Phase 0 inventory crawl.
- Symptom: the command could run for several minutes with no terminal output and appear stalled.
- Cause: `--max-pages` limited listing pages only; the crawler still followed discovered dataset/documentation pages and probed assets, with per-request delays and retry backoff.
- Resolution: add follow-up limits, asset limits, duplicate asset probe suppression, and CLI progress output.
- Prevention: use `--max-follow-pages` and `--max-assets` for smoke tests, and leave progress output enabled unless running in a quiet automation context.

### Archive retries should reuse preserved raw files

- Context: full ResDAC archive pass after a successful 339-row inventory crawl.
- Symptom: the first archive run preserved 297 files but exited nonzero after later ResDAC HTML requests returned HTTP 429.
- Cause: the archive pass retried transient statuses but had no resume path, so rerunning would re-download already preserved files and increase throttling risk.
- Resolution: reuse existing non-empty raw files when rebuilding the archive manifest, then retry only missing targets with a larger request delay.
- Prevention: after archive throttling, inspect `_workspace/03_archive_manifest.md`, keep existing `data/raw/` files, and rerun `cms-kb-archive` with a slower delay instead of deleting outputs.

### Listing-sourced assets can still belong to datasets

- Context: retained KB rebuild from the checked-in ResDAC archive snapshot.
- Symptom: metadata extraction returned failures for archived PDF assets whose manifest `source_url` pointed to a listing page.
- Cause: the assets were linked from archived dataset pages, but the inventory row kept the listing page as the immediate source.
- Resolution: resolve asset-to-dataset ownership by scanning archived dataset-page links when manifest `source_url` is not a dataset page.
- Prevention: when extraction reports "document source is not linked to a dataset page", search archived dataset HTML for the asset URL before treating it as orphaned.

### XLSX assets are first-class parse inputs

- Context: retained KB rebuild after metadata extraction included XLSX document rows.
- Symptom: parsing wrote HTML/PDF chunks but exited nonzero with unsupported `xlsx` document kind failures.
- Cause: the checked-in archive includes spreadsheet record layouts, and parsing originally handled only HTML and PDF documents.
- Resolution: parse XLSX files from workbook XML/shared strings with the Python standard library and write parsed text plus chunks.
- Prevention: include `data/parsed/xlsx/` in parsed artifact checks and rerun `cms-kb-parse` after changing document-kind support.

### Variable-detail archive batches can hit ResDAC rate limits

- Context: retained corpus refresh after adding standalone variable-detail pages from data-documentation tables.
- Symptom: inventory/archive runs appeared stalled while sleeping after HTTP 429 responses, and a full variable-page archive returned many 429 failures.
- Cause: data-documentation pages link thousands of variable-detail URLs, and bulk fetching those pages triggers ResDAC rate limiting.
- Resolution: record variable-page URLs during inventory without fetching them, let archive own the actual download/status manifest, and fail fast on 429 instead of sleeping indefinitely.
- Prevention: prioritize required variable pages for smoke validation, inspect `_workspace/03_archive_manifest.md` for rate-limited variable rows, and rerun archive later for missing variable-page coverage instead of blocking extraction/QA.

### Phase 1 archive recovery should be bounded and resumable

- Context: rerunning Phase 1 after ResDAC returned thousands of HTTP 429/deferred variable-page failures.
- Symptom: a plain archive rerun could revisit too many URLs and quickly trigger rate limiting again.
- Cause: successful raw files and failed rows share the same full archive manifest, so the operator needs retry controls that preserve prior provenance while limiting new network attempts.
- Resolution: use `uv run cms-kb-archive --retry-failed-only --max-downloads 50 --request-delay-seconds 5 --rate-limit-cooldown-seconds 300` to retry failed rows in batches.
- Prevention: keep the previous manifest and `data/raw/` files in place, use bounded retry-only batches after 429s, and inspect `_workspace/03_archive_manifest.md` between batches.
