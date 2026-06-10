# ARCHITECTURE

## Overview
The repository is currently a documentation-first knowledge base for CMS and ResDAC materials. The canonical repo state is the archived source material, extracted metadata, and provenance-bearing manifests that future code will generate.

Last Reviewed: 2026-06-10
Status: Verified

## Main Surfaces
- `README.md`: project motivation, scope, and the intended multi-phase system.
- `ROADMAP.md`: phased execution plan for archive, extraction, parsing, graph, retrieval, and evaluation work.
- `docs/harness/cms-kb/team-spec.md`: repo-local orchestration contract for archive, extraction, and QA handoffs.
- `data/`: canonical durable outputs when the pipeline exists, especially raw archives, metadata, and graph artifacts.
- `manifests/`: inventory and provenance manifests for downloaded or parsed sources.
- `src/`: implementation surface for crawl, archive, parse, metadata, graph, retrieval, and evaluation code.
- `tests/`: verification for archive integrity, extraction accuracy, and retrieval behavior.

## Data Flow
1. Discover source pages and files from ResDAC and related CMS documentation sites.
2. Archive raw HTML, PDFs, spreadsheets, and attachments with checksums and source URLs.
3. Extract structured metadata and relationships from the archived corpus.
4. Persist provenance-bearing artifacts in `data/`, `manifests/`, and related stores.
5. Expose search and retrieval layers that always retain citations back to source documents.

## Constraints
- Preserve source material before transforming it.
- Keep provenance attached to every derived record.
- Favor small, composable pipeline steps over hidden cross-cutting logic.
- Treat `data/raw/` and manifest outputs as canonical inputs to downstream extraction.
- Do not introduce retrieval outputs that cannot be traced back to a source document.

## Current State
There is no runtime pipeline yet in the repository. The current architecture is the project documentation and harness contract that define the intended shape of the future system.
