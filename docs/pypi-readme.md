# ResDAC Knowledge Base (`resdac-knowledge-base` aka `rkb`)

A Python library and command-line toolkit for crawling, archiving, parsing, and searching public CMS (Centers for Medicare & Medicaid Services) and ResDAC (Research Data Assistance Center) documentation.

It enables researchers, data engineers, and AI agents to query dataset metadata, variable definitions, and document structures offline with strict citation-backed provenance.

## Key Features

- **Offline-First Preservation**: Rebuild the entire knowledge base from pre-packaged raw snapshots containing HTML, PDF, and spreadsheet documentation.
- **Pipeline Processing**: Pipeline commands to crawl/inventory, archive, parse, extract variables, and perform quality assurance audits.
- **Lexical Search**: Query the compiled SQLite FTS5 index for variables, datasets, and document chunks.
- **Model Context Protocol (MCP) Support**: Run an MCP server to connect the knowledge base directly to AI editors and tools (e.g., Claude Desktop, Cursor).
- **Provenance-First Design**: Every retrieved definition or document chunk is mapped back to its source URL and local archived path.

## Installation

Install using `pip` or `uv`:

```bash
pip install resdac-knowledge-base
```

For optional semantic search support:

```bash
pip install "resdac-knowledge-base[semantic]"
```

## Quick Start

### 1. Build the Search Index
Before querying, compile the SQLite FTS5 search index:

```bash
cms-kb-index
```

### 2. Search variables & definitions
Query the search index using the command-line interface:

```bash
cms-kb-search --query "BENE_ID" --limit 5
```

### 3. Expose as MCP Server
Start the Model Context Protocol server to connect your AI assistant:

```bash
cms-kb-mcp
```

See more options and entry points/paths in the [user manual](docs/user-manual.md).

## Programmatic API Example

You can query the knowledge base and retrieve citation-packed context directly in Python:

```python
from pathlib import Path
from cms_kb import AgentContextConfig, build_agent_context

# Configure paths to manifests and search indices
config = AgentContextConfig(
  archive_manifest_path=Path("manifests/archive_manifest.csv")
)

# Search for a variable and print definition and source citation
response = build_agent_context(config, query="DUAL_ELG", limit=1)

for hit in response.results:
  print(f"Record: {hit.title} ({hit.record_type})")
  print(f"Snippet: {hit.snippet}")
  print(f"Source URL: {hit.citation.source_url}")
  if hit.citation.variable_document:
    print(f"Local Archive Path: {hit.citation.variable_document}")
```

## Documentation

For full details on the data model, pipeline steps, and development guidelines, refer to the repository documentation:
- [User Manual](https://github.com/SaehwanPark/resdac-knowledge-base/docs/user-manual.md)
- [Developer Guide](https://github.com/SaehwanPark/resdac-knowledge-base/docs/developer-guide.md)
- [Data Model Reference](https://github.com/SaehwanPark/resdac-knowledge-base/docs/data-model.md)
