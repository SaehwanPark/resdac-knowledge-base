---
name: cms-kb-extraction
description: Convert archived CMS documentation into metadata, entities, and graph seeds with preserved provenance.
---

# CMS KB Extraction Specialist

## When to use

- Use after archive provenance exists and the source set is stable.
- Use when the task is to extract datasets, variables, relationships, or other structured metadata.
- Do not use as a substitute for archival work or QA review.

## Required inputs

- A stable archive manifest.
- Source document paths or URLs.
- The metadata shape expected by the downstream knowledge base.

## Workflow

1. Read the source documents from the archive manifest.
2. Extract dataset, program, document, variable, and relationship records.
3. Write the intermediate extraction summary to `_workspace/04_extraction_pack.md`.
4. Preserve source references for every extracted fact.
5. Leave unresolved or ambiguous mappings explicitly marked for QA review.

## Expected outputs

- `_workspace/04_extraction_pack.md`
- A metadata pack suitable for the repo's future structured storage layer.
- A graph seed that preserves provenance on each edge or entity.

## Validation notes

- No extracted fact is valid without a source reference.
- If a field cannot be normalized, keep the original text and flag it.
- Keep the extraction shape stable so QA can compare runs.

## Stop conditions

- Stop if the archive manifest is incomplete.
- Stop if the source document path cannot be verified.
- Stop if provenance would be lost during normalization.

