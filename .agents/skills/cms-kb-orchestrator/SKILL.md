---
name: cms-kb-orchestrator
description: Coordinate CMS documentation archival, extraction, and provenance review with deterministic file handoffs.
---

# CMS KB Orchestrator

## When to use

- Use for any CMS documentation workflow that needs ordered phases and durable review artifacts.
- Use when a request may touch discovery, archival, metadata extraction, or citation review in the same run.
- Do not use for one-off ad hoc questions that can be answered from a single existing artifact.

## Required inputs

- Source scope: which CMS or ResDAC entry points are in scope.
- Desired deliverable: archive manifest, metadata pack, graph seed, or provenance review.
- Quality bar: what must be cited, preserved, or summarized before handoff.
- Stop condition: what should cause the run to pause instead of guessing.

## Workflow

1. Write `_workspace/01_request.md` with the request scope, source scope, and acceptance criteria.
2. Route the request to `cms-kb-archive` if the work needs discovery, downloading, or checksum capture.
3. Route the request to `cms-kb-extraction` after archive provenance exists and the source set is stable.
4. Route the request to `cms-kb-qa` before any output is treated as trusted.
5. Record the final state in `_workspace/05_qa_review.md` and stop if QA returns `fix` or `redo`.

## Expected outputs

- `_workspace/01_request.md`
- `_workspace/02_source_inventory.md`
- `_workspace/03_archive_manifest.md`
- `_workspace/04_extraction_pack.md`
- `_workspace/05_qa_review.md`

## Validation notes

- Keep the phase order fixed: request -> inventory -> archive -> extraction -> QA.
- Keep handoff filenames stable so later agents can replay the run without guessing.
- If a phase needs a new artifact name, update the team spec and validator together.

## Stop conditions

- Stop if a phase cannot name its input and output artifact.
- Stop if provenance is missing and the agent is tempted to infer it.
- Stop if the workflow starts requiring a second coordinator or a backlog queue.

