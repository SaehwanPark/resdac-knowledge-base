# CMS Documentation Knowledge Base - User Manual

Welcome to the CMS Documentation Knowledge Base! This manual is designed for health policy researchers, scientists, analysts, developers, and AI agents who need to navigate, search, and understand public CMS and ResDAC data structures.

The knowledge base is built to be a reliable, offline-first, citation-backed repository of CMS documentation. It ensures that whenever you ask a question or search for a variable, you get a direct answer backed by the exact source document, page number, and URL it came from.

---

## 1. Core Concepts & Data Model

To make the most of this knowledge base, it is helpful to understand the primary types of records stored in the system:

*   **Datasets**: High-level CMS data products (e.g., Medicare Beneficiary Summary File, Part D Event Data).
*   **Documents**: Documentation pages, user guides, codebooks, spreadsheets, and PDFs linked to datasets.
*   **Variables**: Specific data elements (e.g., `BENE_ID`, `MSIS_ID`, `CLM_ID`) along with definitions, years of availability, and source references.
*   **Canonical Variables**: Standalone ResDAC variable-detail pages representing a semantic variable that may connect to multiple datasets.
*   **Graph Seeds**: Pre-defined relationships linking programs, datasets, documents, and variables together.
*   **Parsed Chunks**: Small, searchable segments of text extracted from raw HTML, PDF, or Excel documents, mapping back to their original page number or source document.
*   **Citations**: The specific URL, local file path, and page number proving where an extracted fact or variable definition was found.

### Knowledge Graph Schema
The relationships among records form a lightweight knowledge graph:
```text
Dataset -> belongs_to -> Program
Dataset -> documented_by -> Document
Dataset -> contains -> Variable
Dataset -> contains -> CanonicalVariable
Dataset -> related_to -> Dataset
```

---

## 2. Rebuilding the Knowledge Base Offline (No Network Required)

This repository is designed with an **offline-first preservation model**. A complete, raw snapshot of the ResDAC public documentation corpus is pre-packaged and checked directly into the repository under `data/raw/` and `manifests/`.

Because the raw documents are already local, **you do not need to fetch or crawl anything from ResDAC to build or run the knowledge base.** You can extract metadata, parse documents, and build the search indices entirely offline.

### Offline Build Steps

To run the pipeline and generate a new snapshot of the knowledge base from scratch, execute the following commands in sequence:

#### Step 0: Set Up Environment and Dependencies
Verify you have Python >= 3.13 and `uv` installed, then run:
```bash
uv sync
uv run pytest
```
*Ensures all dependencies are locked and local unit tests pass.*

#### Step 1: Run Metadata and Ontology Extraction
Processes the raw HTML to identify datasets, document groupings, program assignments, and network categories:
```bash
uv run cms-kb-extract
```
*   **Input**: `data/raw/html/` and `manifests/archive_manifest.csv`
*   **Outputs**:
    - `data/metadata/datasets.csv` (High-level dataset metadata)
    - `data/metadata/documents.csv` (Document listings)
    - `data/graph/document_edges.csv` (Dataset-to-document relationships)
    - `data/graph/ontology_nodes.csv` (Program and category graph nodes)
    - `data/graph/ontology_edges.csv` (Program-to-dataset relationships)
    - `_workspace/04_extraction_pack.md` (Extraction run summary)

#### Step 2: Parse Documents and Generate Text Chunks
Converts archived HTML, PDF, and XLSX files into raw text files and segments them into retrieval-size chunks with metadata:
```bash
uv run cms-kb-parse
```
*   **Input**: `data/raw/` assets, `data/metadata/documents.csv`
*   **Outputs**:
    - `data/parsed/html/...` (Extracted HTML text)
    - `data/parsed/pdf/...` (Extracted PDF text)
    - `data/parsed/xlsx/...` (Extracted Excel spreadsheet text)
    - `data/parsed/chunks/` (Individual retrieval JSON chunks)
    - `data/parsed/chunks.jsonl` (Unified JSONL stream of all chunks)
    - `_workspace/05_parsing_pack.md` (Parsing run summary)

#### Step 3: Run Variable-Level Extraction
Extracts variable definitions, years, and aliases from parsed text chunks:
```bash
uv run cms-kb-variables
```
*   **Input**: `data/parsed/chunks.jsonl`
*   **Outputs**:
    - `data/metadata/variables.csv` (Variable definitions, years, and aliases)
    - `data/metadata/canonical_variables.csv` (Canonical variable attributes)
    - `data/graph/variable_edges.csv` (Variable relationships)
    - `data/graph/data_source_variable_edges.csv` (Variable-to-dataset connections)
    - `_workspace/07_variable_pack.md` (Variable extraction summary)

#### Step 4: Quality Assurance Audit
Runs reference and checksum checks to verify that every record contains valid citations and matches its checksum:
```bash
uv run cms-kb-qa
```
*   **Input**: Metadata and graph outputs from Steps 1-3.
*   **Outputs**:
    - `_workspace/06_qa_review.md` (QA verdict and provenance analysis)

---

## 3. Optional: Live Network Archiving (Fetching from ResDAC)

If you need to update the local raw files with live updates from the ResDAC website, you can run the live crawls. 

> [!WARNING]
> **ResDAC Rate Limiting**: ResDAC aggressively rate-limits bulk downloads when fetching thousands of standalone variable-detail pages. Running these commands will make network requests and may result in HTTP 429 responses. The pipeline is designed to back off and defer variable pages after repeated rate limits, leaving explicit coverage gaps in the manifest that do not block downstream steps.

### Phase 0: Site Discovery (Inventory)
Crawls the ResDAC data catalog listing pages to discover dataset and documentation links:
```bash
uv run cms-kb --max-listing-pages 10 --request-delay-seconds 1.0
```
*   **Outputs**:
    - `manifests/site_inventory.csv` (Discovered inventory rows)
    - `manifests/site_inventory_edges.csv` (Graph edges)
    - `_workspace/02_source_inventory.md` (Discovery summary)

### Phase 1: Local Archival Preservation
Downloads raw HTML pages and linked assets locally, using checksum preservation to reuse local files on rerun:
```bash
uv run cms-kb-archive --request-delay-seconds 1.0
```
*   **Outputs**:
    - `data/raw/html/` & `data/raw/assets/` (New downloads)
    - `manifests/archive_manifest.csv` (Archive state and checksums)
    - `_workspace/03_archive_manifest.md` (Archival summary)

To recover deferred/failed rate-limited variable pages in small, polite batches:
```bash
uv run cms-kb-archive \
  --retry-failed-only \
  --max-downloads 100 \
  --request-delay-seconds 5 \
  --rate-limit-cooldown-seconds 300
```

---

## 4. Querying and Searching the Knowledge Base

Once the knowledge base is built, you can query across all datasets, documents, variables, and parsed text chunks using the search interface.

### Running Search Queries
You can perform lexical search queries directly from your terminal:
```bash
uv run cms-kb-search --query BENE_ID --limit 5 --json
```

### Understanding Search Results
Search results return structured JSON containing:
1.  `record_id`: A unique identifier for the result.
2.  `record_type`: Whether the hit is a `dataset`, `document`, `variable`, or text `chunk`.
3.  `title`: The name of the record.
4.  `snippet`: A brief excerpt showing where the query matched.
5.  `citation`: The exact source provenance, including:
    -   `source_url`: The public web address where the documentation lives.
    -   `source_document`: The local archived file location.
    -   `page`: The page number (for PDF documents) where the text was found.

#### Example Search Result:
```json
{
  "record_id": "mbsf__bene_id",
  "record_type": "variable",
  "title": "BENE_ID",
  "dataset_id": "mbsf",
  "score": 1.25,
  "snippet": "BENE_ID - Encrypted Master Beneficiary ID. This variable uniquely identifies a beneficiary...",
  "citation": {
    "source_url": "https://resdac.org/cms-data/variables/bene-id",
    "source_document": "data/raw/html/dataset_page/mbsf.html",
    "page": null
  }
}
```

### Answering Common Research Questions

Here are examples of health policy research questions the knowledge base helps resolve, along with the queries you can run:

#### A. "Which files contain Medicare Advantage encounter information?"
```bash
uv run cms-kb-search --query "encounter" --limit 5
```
*Surfaces datasets like the Medicare Advantage Encounter Data, along with associated user guides.*

#### B. "Where is dual eligibility documented?"
```bash
uv run cms-kb-search --query "dual eligibility" --limit 5
```
*Returns variables like `DUAL_ELG` and documentation chunks detailing Medicaid/Medicare dual-eligibility linkage.*

#### C. "What are the availability years and definition for BENE_ID?"
```bash
uv run cms-kb-search --query "BENE_ID" --limit 3
```
*Returns variable records detailing the definition, aliases, and specific years of availability.*

---

## 5. AI Agent & Copilot Integration (MCP Server)

For users utilizing AI assistants (such as Claude Desktop or custom LLM clients), this knowledge base includes a **Model Context Protocol (MCP)** server. 

The MCP server allows your AI agent to interact directly with the local knowledge base, making it a "CMS Research Copilot" that can retrieve documentation and citations without hallucinating.

### Exposed Agent Tools
The AI assistant can invoke the following tools:
*   `search_datasets(query, limit)`: Searches high-level CMS dataset metadata.
*   `search_documents(query, limit)`: Searches attached documentation references.
*   `search_variables(query, limit)`: Searches variable-level metadata.
*   `search_chunks(query, limit)`: Searches the full text of all parsed HTML, PDF, and Excel documents.
*   `get_agent_context(query, limit)`: Returns a unified, citation-preserving retrieval context hit stream.

### Running the Server Locally
To start the MCP server in standard I/O mode:
```bash
uv run cms-kb-mcp
```

### Claude Desktop Integration
To configure Claude Desktop to use the server, add the following to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "cms-knowledge-base": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/saehwan/repos/resdac-knowledge-base",
        "run",
        "cms-kb-mcp"
      ]
    }
  }
}
```

---

## 6. Monitoring and Tools

### Monitoring Long Runs
Inventory (`cms-kb`) and archive (`cms-kb-archive`) write JSONL progress logs under `_workspace/` by default. You can inspect the progress dynamically:
```bash
# Tail progress logs
tail -f _workspace/03_archive_progress.jsonl

# Run progress summary tool
uv run cms-kb-progress _workspace/03_archive_progress.jsonl --lines 50
```

---

## 7. Trust and Provenance

Every dataset, document, and variable in the knowledge base is verified:
*   **Checksum Verification**: All archived source files (HTML, PDFs, spreadsheets) are hashed (SHA-256) and recorded in `manifests/archive_manifest.csv`.
*   **No Hallucinations**: Downstream extraction tools are restricted to documented facts. If a provenance trail is missing or ambiguous, the pipeline is designed to skip or raise validation errors rather than guess.
*   **Reproducibility**: You can rebuild the entire metadata and search index locally at any time from the archived raw source files.
