# KB Rebuild Request

Run date: 2026-06-12

## Request Scope

Build and retain the CMS/ResDAC knowledge-base artifacts from the current
checked-in archive snapshot. Verify every pipeline phase and keep `STATUS.md`
updated after each completed step.

## Source Scope

- Use the existing checked-in ResDAC archive snapshot as the durable source.
- Do not perform a full live ResDAC refresh in this slice.
- Use a bounded live inventory/archive smoke test only to verify Phase 0 and
  Phase 1 commands still work.

## Artifact Retention

Retain generated pipeline artifacts in git when the run succeeds:

- `data/metadata/`
- `data/graph/`
- `data/parsed/`
- `_workspace/` phase handoff files

## Acceptance Criteria

- Preflight checks pass before generation.
- Phase 0 and Phase 1 live smoke commands complete using temporary paths.
- Metadata, graph, parsed chunks, and variable artifacts are generated from the
  checked-in archive snapshot.
- QA returns a passing verdict.
- Retrieval and agent-context smoke queries return citation-preserving JSON.
- Final checks pass.
- `STATUS.md` records command results and retained artifact counts.

## Stop Conditions

- Stop if a phase cannot name its input and output artifact.
- Stop if QA returns `redo`.
- Stop if provenance fields are missing and would require inference.
- Stop if a failure requires broad redesign beyond a focused phase fix.
- Stop if generated artifacts are unexpectedly too large for practical
  retention.
