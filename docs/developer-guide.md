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
| `cms-kb-index` | `cms_kb.retrieval` | `data/index/retrieval.sqlite` | Compiles the SQLite FTS5 serving index |
| `cms-kb-agent-context` | `cms_kb.agent_api` | stdout (JSON) | Retrieval context CLI with citation mapping |
| `cms-kb-mcp` | `cms_kb.mcp` | stdio / HTTP / log | Model Context Protocol (MCP) server (supports start/stop/status background daemon commands) |
| `cms-kb-progress` | `cms_kb.progress` | stdout | Summarize tail of inventory/archive progress JSONL |

---

## 4. Rebuilding the Knowledge Base

To run the pipeline and generate a new snapshot of the knowledge base from scratch, execute the following commands in sequence:

### Step 0: Site Discovery (Inventory)
Builds the inventory listing containing dataset URLs, title attributes, content types, and asset paths:

```bash
uv run cms-kb --max-listing-pages 10 --request-delay-seconds 1.0
```
*Creates: `manifests/site_inventory.csv`, `manifests/site_inventory_edges.csv`, and `_workspace/02_source_inventory.md`.*

### Step 1: Local Archival Preservation
Downloads raw HTML pages and linked documents/spreadsheets, using checksum preservation to reuse local files on rerun:

```bash
uv run cms-kb-archive --request-delay-seconds 0.5
```
*Creates: `data/raw/` downloads, `manifests/archive_manifest.csv`, and `_workspace/03_archive_manifest.md`.*

> [!WARNING]
> **ResDAC Rate Limiting Caveat**: ResDAC aggressively rate-limits bulk downloads when fetching thousands of standalone variable-detail pages.
> The archive tool retries `429 Too Many Requests` politely, respects `Retry-After` when provided, and defers remaining variable-page requests after repeated 429s.
> Rate-limited and deferred rows are retained in `manifests/archive_manifest.csv` and `_workspace/03_archive_manifest.md`.
> Extraction, parsing, and QA are designed to tolerate these failures, allowing downstream steps to pass even with partial variable-page coverage. Iterative rerun of `cms-kb-archive` will attempt to fetch missing pages.

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
*Creates: `data/metadata/variables.csv`, `data/metadata/canonical_variables.csv`, `data/graph/variable_edges.csv`, `data/graph/data_source_variable_edges.csv`, and `_workspace/07_variable_pack.md`.*

### Step 5: Quality Assurance Audit
Runs reference and checksum checks to verify that every record contains valid citations, local paths, and matches its checksum:

```bash
uv run cms-kb-qa
```
*Creates: `_workspace/06_qa_review.md`.*

### Step 6: SQLite Index Compilation
Compiles the final SQLite FTS5 serving index from the generated metadata catalogs and parsed text chunks:

```bash
uv run cms-kb-index
```
*Creates: `data/index/retrieval.sqlite`.*

---

## 5. Monitoring Long Runs

Inventory (`cms-kb`) and archive (`cms-kb-archive`) write JSONL progress logs
under `_workspace/` by default. Each run **truncates** its log file at start so
tails reflect the current run only.

| Stage | Default progress log |
| :--- | :--- |
| Inventory | `_workspace/02_inventory_progress.jsonl` |
| Archive | `_workspace/03_archive_progress.jsonl` |

During a run:

```bash
tail -f _workspace/03_archive_progress.jsonl
```

For a structured summary of recent events:

```bash
uv run cms-kb-progress _workspace/03_archive_progress.jsonl --lines 50
uv run cms-kb-progress _workspace/03_archive_progress.jsonl --lines 20 --json
```

Archive flags:

- `--progress-interval 25` — emit rollup `progress` events and stderr status lines every N processed inventory rows (`0` disables rollups).
- `--no-progress-log` — disable JSONL file output entirely.

Per-row events (`download_success`, `rate_limited`, `skip`, etc.) remain in the
JSONL log for detailed tails. Periodic `progress` events include cumulative
counts such as `rows_processed`, `archived`, `failed`, and `download_attempts`.

---

## 6. Exposing the MCP Server

The server implements the Model Context Protocol to serve the retrieved outputs. It runs in `stdio` mode and can be integrated into AI editors (e.g., Cursor, Windsurf) or client applications (e.g., Claude Desktop).

### Automatic Setup (Setup Wizard)

Developers can use the configuration wizard to configure client applications automatically:
```bash
uv run cms-kb-mcp-setup
```
Refer to the [user-manual.md](user-manual.md) for more details.

### Running the Server locally

The server supports two execution modes:

#### Foreground Mode (stdio)
```bash
uv run cms-kb-mcp
```

#### Background Daemon Mode (start/stop/status)
```bash
# Start background server (runs as SSE HTTP server by default)
uv run cms-kb-mcp start --port 8000

# Inspect server status
uv run cms-kb-mcp status

# Stop background server
uv run cms-kb-mcp stop
```

### Configuration Options
The server CLI accepts the following configuration flags:

*   `command`: Optional action (`start`, `stop`, `status`). If omitted, starts in the foreground.
*   `--transport`: Transport protocol to use (`stdio`, `sse`, or `streamable-http`). Defaults to `stdio` for foreground, and `sse` for background daemon.
*   `--host`: Host to bind the SSE server to (default: `127.0.0.1`).
*   `--port`: Port to bind the SSE server to (default: `8000`).
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

Every stage of the pipeline outputs a markdown file under `_workspace/` summarizing its execution. These files are used by agents and operators to audit intermediate steps:

*   `_workspace/01_request.md`: The initial query scope.
*   `_workspace/02_source_inventory.md`: Discovered dataset URLs and coverage bounds.
*   `_workspace/03_archive_manifest.md`: Status of raw downloads and checksum matches.
*   `_workspace/04_extraction_pack.md`: Metrics for extracted datasets, documents, and ontology edges.
*   `_workspace/05_parsing_pack.md`: Metrics for parsed formats and chunk generation.
*   `_workspace/06_qa_review.md`: Automated audits showing the pass/fail verdict.
*   `_workspace/07_variable_pack.md`: Summary of extracted variables, candidates skipped, and exceptions.
