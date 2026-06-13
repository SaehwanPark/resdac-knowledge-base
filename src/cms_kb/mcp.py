"""Model Context Protocol (MCP) server for CMS KB retrieval and agent context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .agent_api import AgentCitation, AgentContextHit, AgentContextResponse
from .retrieval import (
  RetrievableRecord,
  RetrievalConfig,
  load_retrievable_records,
  search_records,
)


class ServerState:
  def __init__(self) -> None:
    self._config = RetrievalConfig()
    self.default_limit: int = 5
    self._records: list[RetrievableRecord] | None = None

  @property
  def config(self) -> RetrievalConfig:
    return self._config

  @config.setter
  def config(self, value: RetrievalConfig) -> None:
    self._config = value
    self._records = None  # Invalidate cached records

  def get_records(self) -> list[RetrievableRecord]:
    if self._records is None:
      self._records = load_retrievable_records(self._config)
    return self._records


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
  records = state.get_records()
  filtered = [r for r in records if r.record_type == "dataset"]
  results = search_records(query, filtered, resolved_limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_documents(query: str, limit: int | None = None) -> str:
  """Search document records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  records = state.get_records()
  filtered = [r for r in records if r.record_type == "document"]
  results = search_records(query, filtered, resolved_limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_variables(query: str, limit: int | None = None) -> str:
  """Search variable records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  records = state.get_records()
  filtered = [r for r in records if r.record_type == "variable"]
  results = search_records(query, filtered, resolved_limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_chunks(query: str, limit: int | None = None) -> str:
  """Search parsed text chunks in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  records = state.get_records()
  filtered = [r for r in records if r.record_type == "chunk"]
  results = search_records(query, filtered, resolved_limit)
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def get_agent_context(query: str, limit: int | None = None) -> str:
  """Get citation-preserving agent context hits for a search query.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  records = state.get_records()
  results = search_records(query, records, resolved_limit)
  hits = [
    AgentContextHit(
      record_id=res.record_id,
      record_type=res.record_type,
      title=res.title,
      dataset_id=res.dataset_id,
      score=res.score,
      snippet=res.snippet,
      citation=AgentCitation(
        source_url=res.source_url,
        source_document=res.source_document,
        page=res.page,
      ),
    )
    for res in results
  ]
  response = AgentContextResponse(query=query, results=hits)
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

  if not args.datasets_metadata.is_file():
    print(f"Error: Datasets metadata file not found at {args.datasets_metadata}", file=sys.stderr)
    return 1
  if not args.documents_metadata.is_file():
    print(f"Error: Documents metadata file not found at {args.documents_metadata}", file=sys.stderr)
    return 1

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
