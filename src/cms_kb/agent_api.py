"""Agent-facing context retrieval API for CMS KB records."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import sys
from pathlib import Path
from urllib.parse import urljoin

from pydantic import BaseModel

from .retrieval import RetrievalConfig, SearchResult, run_retrieval


class AgentContextConfig(BaseModel):
  retrieval: RetrievalConfig = RetrievalConfig()
  default_limit: int = 5


class AgentCitation(BaseModel):
  source_url: str
  source_document: str = ""
  page: int | None = None
  variable_url: str = ""
  variable_document: str = ""


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


class _VariableLinkParser(HTMLParser):
  def __init__(self) -> None:
    super().__init__()
    self.rows: list[list[tuple[str, str]]] = []
    self._current_row: list[tuple[str, str]] | None = None
    self._current_cell_text: list[str] | None = None
    self._current_cell_href = ""

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    if tag == "tr":
      self._current_row = []
      return
    if tag in {"td", "th"} and self._current_row is not None:
      self._current_cell_text = []
      self._current_cell_href = ""
      return
    if tag == "a" and self._current_cell_text is not None:
      href = dict(attrs).get("href") or ""
      if href:
        self._current_cell_href = href

  def handle_endtag(self, tag: str) -> None:
    if tag in {"td", "th"} and self._current_row is not None:
      text = " ".join("".join(self._current_cell_text or []).split())
      self._current_row.append((text, self._current_cell_href))
      self._current_cell_text = None
      self._current_cell_href = ""
      return
    if tag == "tr" and self._current_row is not None:
      if self._current_row:
        self.rows.append(self._current_row)
      self._current_row = None

  def handle_data(self, data: str) -> None:
    if self._current_cell_text is not None:
      self._current_cell_text.append(data)


def _find_variable_link(result: SearchResult) -> tuple[str, str]:
  source_document = Path(result.source_document)
  if result.record_type != "variable" or not source_document.is_file():
    return "", ""

  if "/cms-data/variables/" in result.source_url:
    return result.source_url, result.source_document

  try:
    html = source_document.read_text(encoding="utf-8", errors="replace")
  except OSError:
    return "", ""

  parser = _VariableLinkParser()
  parser.feed(html)
  for row in parser.rows:
    cell_texts = [text.strip() for text, _ in row]
    if result.title not in cell_texts:
      continue
    for _, href in row:
      if "/cms-data/variables/" in href:
        return urljoin("https://resdac.org", href), ""
  return "", ""


def context_hit_from_search_result(result: SearchResult) -> AgentContextHit:
  variable_url, variable_document = _find_variable_link(result)
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
      variable_url=variable_url,
      variable_document=variable_document,
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
    results=[context_hit_from_search_result(result) for result in results],
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
  "context_hit_from_search_result",
  "main",
]
