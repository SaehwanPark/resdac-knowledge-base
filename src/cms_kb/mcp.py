"""Model Context Protocol (MCP) server for CMS KB retrieval and agent context.

This module implements an MCP server using FastMCP. It exposes tool wrappers
allowing external LLM agents and clients to query the local CMS Knowledge Base
interactively. The tools provide search capabilities over datasets, documents,
variables, and parsed text chunks, including citation-preserving context hits.

Architecture & State Management:
- The `ServerState` object acts as an in-memory database cache. Since loading
  thousands of records from CSV/JSONL files on every query would be slow,
  `ServerState` caches the parsed metadata list and the archive document mappings.
- Setting any configuration path invalidates the cache dynamically.
- Execution runs on the `stdio` transport layer, enabling easy integration with
  MCP-compliant host applications.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .agent_api import (
  AgentContextResponse,
  context_hit_from_search_result,
  read_archived_document_map,
)
from .retrieval import (
  RetrievableRecord,
  RetrievalConfig,
  load_retrievable_records,
  run_retrieval,
)


class ServerState:
  """Caches and manages the in-memory metadata state for the MCP server.

  This avoids expensive re-reads of the CSV and JSONL source files on
  each tool invocation. Modifying configurations invalidates cached objects.
  """

  def __init__(self) -> None:
    self._config = RetrievalConfig()
    self._archive_manifest_path = Path("manifests/archive_manifest.csv")
    self.default_limit: int = 5
    self._records: list[RetrievableRecord] | None = None
    self._archived_documents_by_url: dict[str, str] | None = None

  @property
  def config(self) -> RetrievalConfig:
    """The search and index configuration settings."""
    return self._config

  @config.setter
  def config(self, value: RetrievalConfig) -> None:
    self._config = value
    # Invalidate cached records so that they are reloaded with the new configuration
    self._records = None

  def get_records(self) -> list[RetrievableRecord]:
    """Retrieves all indexed metadata records, loading them on-demand if not cached."""
    if self._records is None:
      self._records = load_retrievable_records(self._config)
    return self._records

  @property
  def archive_manifest_path(self) -> Path:
    """The path to the local archive manifest CSV."""
    return self._archive_manifest_path

  @archive_manifest_path.setter
  def archive_manifest_path(self, value: Path) -> None:
    self._archive_manifest_path = value
    # Invalidate cached archive map when the manifest path changes
    self._archived_documents_by_url = None

  def get_archived_documents_by_url(self) -> dict[str, str]:
    """Loads and caches the URL-to-local-path map for offline citation resolution."""
    if self._archived_documents_by_url is None:
      self._archived_documents_by_url = read_archived_document_map(
        self._archive_manifest_path
      )
    return self._archived_documents_by_url


state = ServerState()
mcp = FastMCP("CMS KB Server")


@mcp.tool()
def search_datasets(query: str, limit: int | None = None) -> str:
  """Search dataset records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="dataset")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_documents(query: str, limit: int | None = None) -> str:
  """Search document records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="document")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_variables(query: str, limit: int | None = None) -> str:
  """Search variable records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="variable")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_chunks(query: str, limit: int | None = None) -> str:
  """Search parsed text chunks in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="chunk")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def get_agent_context(query: str, limit: int | None = None) -> str:
  """Get citation-preserving agent context hits for a search query.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit)
  archived_documents_by_url = state.get_archived_documents_by_url()
  hits = [
    context_hit_from_search_result(res, archived_documents_by_url)
    for res in results
  ]
  response = AgentContextResponse(query=query, results=hits)
  return json.dumps(response.model_dump(), indent=2)


def build_arg_parser() -> argparse.ArgumentParser:
  """Constructs the argument parser for starting the MCP server CLI.

  Returns:
    An ArgumentParser instance configured with path and limit defaults.
  """
  parser = argparse.ArgumentParser(
    description="Start the read-only MCP server for CMS KB retrieval."
  )
  parser.add_argument(
    "--datasets-metadata",
    type=Path,
    default=Path("data/metadata/datasets.csv"),
  )
  parser.add_argument(
    "--documents-metadata",
    type=Path,
    default=Path("data/metadata/documents.csv"),
  )
  parser.add_argument(
    "--variables-metadata",
    type=Path,
    default=Path("data/metadata/variables.csv"),
  )
  parser.add_argument(
    "--chunks-jsonl",
    type=Path,
    default=Path("data/parsed/chunks.jsonl"),
  )
  parser.add_argument(
    "--archive-manifest",
    type=Path,
    default=Path("manifests/archive_manifest.csv"),
  )
  parser.add_argument(
    "--database-path",
    type=Path,
    default=Path("data/index/retrieval.sqlite"),
  )
  parser.add_argument("--limit", type=int, default=5)
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI execution entrypoint to configure and start the MCP server.

  Args:
    argv: Command line arguments. Uses sys.argv if None.

  Returns:
    Exit code: 0 for clean execution, 1 on initialization/runtime errors.
  """
  parser = build_arg_parser()
  args = parser.parse_args(argv)

  if not args.datasets_metadata.is_file():
    print(f"Error: Datasets metadata file not found at {args.datasets_metadata}", file=sys.stderr)
    return 1
  if not args.documents_metadata.is_file():
    print(f"Error: Documents metadata file not found at {args.documents_metadata}", file=sys.stderr)
    return 1

  # Initialize state values with command line overrides
  state.config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
    database_path=args.database_path,
  )
  state.archive_manifest_path = args.archive_manifest
  state.default_limit = args.limit

  try:
    # Run the FastMCP server utilizing stdio transport communication
    mcp.run("stdio")
  except Exception as exc:
    print(f"Error running MCP server: {exc}", file=sys.stderr)
    return 1

  return 0
