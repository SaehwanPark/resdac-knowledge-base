# Repository Agents Guide

Keep this file short and repo-wide. Use [README.md](/Users/saehwan/repos/resdac-knowledge-base/README.md) and [ROADMAP.md](/Users/saehwan/repos/resdac-knowledge-base/ROADMAP.md) for deeper context.

## What
- CMS documentation knowledge base for archival, metadata extraction, retrieval, and agent support.
- Canonical paths are `data/`, `manifests/`, `src/`, `tests/`, and `docs/`.
- `LESSONS.md` is the repo-local log for recurring setup traps, debugging lessons, and workflow gotchas.
- Use `uv` for all Python dependency and execution workflows.
- Use `pydantic` for validated runtime data models and external-input boundaries.

## Why
- Preserve source documents first, then extract structured metadata with traceable provenance.
- Keep the codebase easy to reason about for agents and humans by favoring pure transforms and explicit data flow.

## How
- Prefer functional programming patterns: pure functions, immutable data where practical, explicit inputs and outputs, and small composable steps.
- Use Railway-oriented programming for fallible flows: keep the happy path linear, return success/failure values instead of throwing deep inside business logic, and isolate side effects at the edges.
- Prefer type-safe programming with `basedpyright`; keep annotations complete enough that static checking stays useful.
- Run Python commands with `uv run ...`; add dependencies with `uv add ...`; sync the environment with `uv sync`.
- Use `ruff` for Python linting and style detection; keep its config in `ruff.toml` and run it with `uv run ruff check .`.
- Run type checks with `uv run basedpyright .` once the Python surface exists.
- Use 2-space indentation everywhere unless a file format requires otherwise. See `.editorconfig`.
- Before handing off work, run the relevant `uv` command for the changed area, then verify the diff is narrow and provenance is preserved.
- When you hit a failure pattern, surprising dependency issue, or non-obvious fix that could recur, add a short factual entry to `LESSONS.md` with context, cause, resolution, and prevention.
- If CLI tool is not found, try running `which <tool>` to find it in the environment.
- You may install missing dependencies with `uv add <package>`.
