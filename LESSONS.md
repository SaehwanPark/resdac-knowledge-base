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
