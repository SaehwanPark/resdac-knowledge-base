---
name: cms-kb-qa
description: Review CMS documentation outputs for provenance, citations, and completeness before they are trusted.
---

# CMS KB QA Specialist

## When to use

- Use after extraction and before any output is treated as trusted.
- Use when the work needs a bounded provenance review, citation audit, or completeness check.
- Do not use to generate new facts; only review what already exists.

## Required inputs

- The extraction pack or metadata pack to review.
- The archive manifest or source inventory used to support the output.
- The acceptance criteria from `_workspace/01_request.md`.

## Workflow

1. Compare each extracted fact against its source reference.
2. Check that source URLs, file names, or document IDs are preserved where required.
3. Write the verdict to `_workspace/05_qa_review.md` using `pass`, `fix`, or `redo`.
4. List every missing citation, broken provenance link, or ambiguous mapping.
5. Block downstream use until the review passes.

## Expected outputs

- `_workspace/05_qa_review.md`
- A clear verdict: `pass`, `fix`, or `redo`.

## Validation notes

- `pass` means provenance is complete enough for downstream use.
- `fix` means the issue is bounded and can be corrected without redoing the source set.
- `redo` means the source inventory or extraction shape is wrong enough to start over.

## Stop conditions

- Stop if a fact cannot be traced to a source.
- Stop if the output is missing the provenance needed for citation-backed use.
- Stop if the review would need to invent new source evidence.

