# LESSONS

Use this file to record recurring setup traps, debugging lessons, and workflow gotchas that would otherwise be easy to repeat.

## Entry Format

- Context: what task or area exposed the issue.
- Symptom: what failed or was confusing.
- Cause: the underlying reason.
- Resolution: what fixed it.
- Prevention: what future contributors should do first.

## Lessons

No lessons recorded yet.

- Context: first live inventory smoke test against `https://resdac.org/cms-data`.
  Symptom: `python` was not on PATH in the repo shell and the first site probes were rate-limited with HTTP 429.
  Cause: the environment expects `uv run python`, and ResDAC briefly throttled rapid repeated requests.
  Resolution: use `uv run python`/`uv run ...` for repo commands and add polite crawl delays plus retry handling for 429/503 responses.
  Prevention: check `which python3`/`which uv` before assuming a `python` entrypoint, and keep live inventory requests throttled.
