# CMS Knowledge Base Developer Guide

This guide is written for software engineers, developers, and data operators who maintain, extend, or run the CMS Knowledge Base pipeline and Model Context Protocol (MCP) server. 

---

## 1. Prerequisites & Environment Setup

This repository uses **`uv`** as the default Python package manager and build tool. 

### System Requirements
*   Python >= 3.13
*   `uv` (Universal Python Tool)

### Setting Up the Environment
To install dependencies, compile packages, and sync your virtual environment, run:

```bash
uv sync
```

### Running Style and Type Checks
Before contributing code, verify it complies with the codebase constraints:

```bash
# Run tests
uv run pytest

# Run Ruff linter (lint-only mode)
uv run ruff check .

# Run static type checking with basedpyright
uv run basedpyright .

# Validate pipeline harness integration
uv run python scripts/validate_harness.py
```

> [!IMPORTANT]
> **Indentation Constraints**: This repository enforces a **2-space indentation policy** across all files (including Python source files). To prevent conflicts, Ruff is configured in **lint-only mode** (do not use `ruff format`, as it defaults to 4 spaces).

---

## 2. Core Codebase Architecture

The codebase is built on three key architectural principles:
1.  **Preservation-First**: Raw assets must be fully archived and checksummed before metadata or chunks are extracted.
2.  **Functional & Type-Safe Patterns**: We favor pure functions with explicit inputs/outputs and immutable data structures. We use **`basedpyright`** for strict static typing and **`pydantic`** for runtime models.
3.  **Railway-Oriented Fallible Flow**: Operations that might fail (e.g., download requests, parse exceptions) return explicit Success/Failure records or tuple outcomes rather than throwing deep exceptions. Side effects are kept isolated at the pipeline edges.

---

## 3. Command-Line Interface (CLI) Reference

The package defines several command-line tools in `pyproject.toml`. Run all commands using `uv run <command>`.

| Command | Entry Point | Primary Output | Description |
| :--- | :--- | :--- | :--- |
| `cms-kb` | `cms_kb.inventory` | `manifests/site_inventory.csv` | Crawls ResDAC site listing to build inventory |
| `cms-kb-archive` | `cms_kb.archive` | `data/raw/` | Downloads HTML and assets locally |
| `cms-kb-extract` | `cms_kb.extraction` | `data/metadata/datasets.csv` | Extracts high-level metadata & ontology seeds |
| `cms-kb-parse` | `cms_kb.parsing` | `data/parsed/` | Extracts text and generates chunk JSONs/JSONL |
| `cms-kb-qa` | `cms_kb.qa` | `_workspace/06_qa_review.md` | Audits checksums, URLs, and references |
| `cms-kb-variables` | `cms_kb.variables` | `data/metadata/variables.csv` | Extracts variable definitions from chunks |
| `cms-kb-search` | `cms_kb.retrieval` | stdout (JSON) | Direct local lexical search CLI |
| `cms-kb-agent-context` | `cms_kb.agent_api` | stdout (JSON) | Retrieval context CLI with citation mapping |
| `cms-kb-mcp` | `cms_kb.mcp` | stdio stream | Model Context Protocol (MCP) server |

---

## 4. Rebuilding the Knowledge Base

To run the pipeline and generate a new snapshot of the knowledge base from scratch, execute the following commands in sequence:

### Step 0: Site Discovery (Inventory)
Builds the inventory listing containing dataset URLs, title attributes, content types, and asset paths:

```bash
uv run cms-kb --max-listing-pages 10 --request-delay-seconds 1.0
```
*Creates: `manifests/site_inventory.csv` and `_workspace/02_source_inventory.md`.*

### Step 1: Local Archival Preservation
Downloads raw HTML pages and linked documents/spreadsheets, using checksum preservation to reuse local files on rerun:

```bash
uv run cms-kb-archive --request-delay-seconds 0.5
```
*Creates: `data/raw/` downloads, `manifests/archive_manifest.csv`, and `_workspace/03_archive_manifest.md`.*

### Step 2: Metadata and Ontology Extraction
Processes the raw HTML to identify datasets, document groupings, program assignments, and network categories:

```bash
uv run cms-kb-extract
```
*Creates: Metadata CSVs under `data/metadata/`, ontology nodes/edges under `data/graph/`, and `_workspace/04_extraction_pack.md`.*

### Step 3: Document Parsing
Converts archived HTML, PDF, and XLSX files into raw text files and segments them into retrieval-size chunks with metadata:

```bash
uv run cms-kb-parse
```
*Creates: `data/parsed/` files, `data/parsed/chunks.jsonl`, and `_workspace/05_parsing_pack.md`.*

### Step 4: Variable-Level Extraction
Extracts variable definitions, years, and aliases from text chunks:

```bash
uv run cms-kb-variables
```
*Creates: `data/metadata/variables.csv`, `data/graph/variable_edges.csv`, and `_workspace/07_variable_pack.md`.*

### Step 5: Quality Assurance Audit
Runs reference and checksum checks to verify that every record contains valid citations, local paths, and matches its checksum:

```bash
uv run cms-kb-qa
```
*Creates: `_workspace/06_qa_review.md`.*

---

## 5. Exposing the MCP Server

The server implements the Model Context Protocol to serve the retrieved outputs. It runs in `stdio` mode and can be integrated into AI editors (e.g., Cursor, Windsurf) or client applications (e.g., Claude Desktop).

### Running the Server locally

```bash
uv run cms-kb-mcp
```

### Configuration Options
The server CLI accepts the following configuration flags:

*   `--datasets-metadata`: Path to `datasets.csv` (default: `data/metadata/datasets.csv`)
*   `--documents-metadata`: Path to `documents.csv` (default: `data/metadata/documents.csv`)
*   `--variables-metadata`: Path to `variables.csv` (default: `data/metadata/variables.csv`)
*   `--chunks-jsonl`: Path to `chunks.jsonl` (default: `data/parsed/chunks.jsonl`)
*   `--limit`: Default maximum search results to return (default: `5`)

### Integrating with Claude Desktop
To add the CMS Knowledge Base to Claude Desktop, add the following entry to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cms-knowledge-base": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/saehwan/repos/resdac-knowledge-base",
        "run",
        "cms-kb-mcp"
      ]
    }
  }
}
```

---

## 6. Workspace Handoff Contract

Every phase of the pipeline outputs a markdown file under `_workspace/` summarizing its execution. These files are used by agents and operators to audit intermediate steps:

*   `_workspace/01_request.md`: The initial query scope.
*   `_workspace/02_source_inventory.md`: Discovered dataset URLs and coverage bounds.
*   `_workspace/03_archive_manifest.md`: Status of raw downloads and checksum matches.
*   `_workspace/04_extraction_pack.md`: Metrics for extracted datasets, documents, and ontology edges.
*   `_workspace/05_parsing_pack.md`: Metrics for parsed formats and chunk generation.
*   `_workspace/06_qa_review.md`: Automated audits showing the pass/fail verdict.
*   `_workspace/07_variable_pack.md`: Summary of extracted variables, candidates skipped, and exceptions.
