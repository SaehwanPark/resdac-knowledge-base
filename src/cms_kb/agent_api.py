"""Agent-facing context retrieval API for CMS KB records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from .retrieval import RetrievalConfig, SearchResult, run_retrieval


class AgentContextConfig(BaseModel):
  retrieval: RetrievalConfig = RetrievalConfig()
  default_limit: int = 5


class AgentCitation(BaseModel):
  source_url: str
  source_document: str = ""
  page: int | None = None


class AgentContextHit(BaseModel):
  record_id: str
  record_type: str
  title: str
  dataset_id: str
  score: float
  snippet: str
  citation: AgentCitation


class AgentContextResponse(BaseModel):
  query: str
  results: list[AgentContextHit]


def _context_hit_from_search_result(result: SearchResult) -> AgentContextHit:
  return AgentContextHit(
    record_id=result.record_id,
    record_type=result.record_type,
    title=result.title,
    dataset_id=result.dataset_id,
    score=result.score,
    snippet=result.snippet,
    citation=AgentCitation(
      source_url=result.source_url,
      source_document=result.source_document,
      page=result.page,
    ),
  )


def build_agent_context(
  config: AgentContextConfig,
  query: str,
  limit: int | None = None,
) -> AgentContextResponse:
  resolved_limit = config.default_limit if limit is None else limit
  results = run_retrieval(config.retrieval, query, resolved_limit)
  return AgentContextResponse(
    query=query,
    results=[_context_hit_from_search_result(result) for result in results],
  )


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Return citation-preserving CMS KB context for agent workflows."
  )
  parser.add_argument("--query", required=True)
  parser.add_argument("--limit", type=int, default=5)
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
  parser.add_argument("--json", action="store_true", help="Emit JSON output.")
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = AgentContextConfig(
    retrieval=RetrievalConfig(
      datasets_metadata_path=args.datasets_metadata,
      documents_metadata_path=args.documents_metadata,
      variables_metadata_path=args.variables_metadata,
      chunks_jsonl_path=args.chunks_jsonl,
    ),
    default_limit=args.limit,
  )

  try:
    response = build_agent_context(config, args.query)
  except Exception as exc:
    print(f"Error building agent context: {exc}", file=sys.stderr)
    return 1

  print(json.dumps(response.model_dump(), indent=2))
  return 0


__all__ = [
  "AgentCitation",
  "AgentContextConfig",
  "AgentContextHit",
  "AgentContextResponse",
  "build_agent_context",
  "main",
]
