"""Model Context Protocol (MCP) server for CMS KB retrieval and agent context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .agent_api import AgentContextConfig, build_agent_context
from .retrieval import (
  RetrievalConfig,
  load_retrievable_records,
  search_records,
)


class ServerState:
  def __init__(self) -> None:
    self.config = RetrievalConfig()
    self.default_limit: int = 5


state = ServerState()
mcp = FastMCP("CMS KB Server")


@mcp.tool()
def search_datasets(query: str, limit: int = 5) -> str:
  """Search dataset records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  records = load_retrievable_records(state.config)
  filtered = [r for r in records if r.record_type == "dataset"]
  results = search_records(query, filtered, limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_documents(query: str, limit: int = 5) -> str:
  """Search document records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  records = load_retrievable_records(state.config)
  filtered = [r for r in records if r.record_type == "document"]
  results = search_records(query, filtered, limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_variables(query: str, limit: int = 5) -> str:
  """Search variable records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  records = load_retrievable_records(state.config)
  filtered = [r for r in records if r.record_type == "variable"]
  results = search_records(query, filtered, limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_chunks(query: str, limit: int = 5) -> str:
  """Search parsed text chunks in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  records = load_retrievable_records(state.config)
  filtered = [r for r in records if r.record_type == "chunk"]
  results = search_records(query, filtered, limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def get_agent_context(query: str, limit: int = 5) -> str:
  """Get citation-preserving agent context hits for a search query.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  agent_config = AgentContextConfig(
    retrieval=state.config,
    default_limit=state.default_limit,
  )
  response = build_agent_context(agent_config, query, limit)
  return json.dumps(response.model_dump(), indent=2)


def build_arg_parser() -> argparse.ArgumentParser:
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
  parser.add_argument("--limit", type=int, default=5)
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)

  state.config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
  )
  state.default_limit = args.limit

  try:
    mcp.run("stdio")
  except Exception as exc:
    print(f"Error running MCP server: {exc}", file=sys.stderr)
    return 1

  return 0
