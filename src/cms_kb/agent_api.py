"""Agent-facing context retrieval API for CMS KB records.

This module acts as the primary query interface for external LLM agents and tools
accessing the CMS Knowledge Base. It coordinates:
1. Executing deterministic lexical queries over the processed data structures
   (datasets, documents, variables, chunks) via the `retrieval` module.
2. Linking variable references back to their source documentation pages or PDFs using
   the archive manifest to preserve provenance.
3. Parsing HTML pages (specifically listing and documentation pages) dynamically
   to locate links that connect variables to their definitions.

Architecture & Component Interactions:
- Downstream LLM agents invoke `build_agent_context` (or run this module via CLI/MCP)
  with a question or query.
- The query triggers `run_retrieval` in `cms_kb.retrieval`, which matches chunks/metadata.
- For matching variable records, we trace their provenance back to the original archived
  sources by reading `manifests/archive_manifest.csv` via `read_archived_document_map`.
- If a retrieved record is of type "variable", we use the custom `_VariableLinkParser`
  (an HTMLParser subclass) to scan the raw archived HTML. This parses layout tables or list
  elements in dataset pages to identify the specific URL corresponding to that variable's detail page.

Known Constraints:
- Variable pages at ResDAC are often dynamically linked or structured inside table columns.
  The `_VariableLinkParser` relies on finding the exact variable title in a table row
  and searching the row for a link pointing to the variable path structure (`/cms-data/variables/`).
"""

from __future__ import annotations

import argparse
import csv
from html.parser import HTMLParser
import json
import sys
from pathlib import Path
from urllib.parse import urljoin

from pydantic import BaseModel

from .paths import get_packaged_data_path
from .retrieval import RetrievalConfig, SearchResult, run_retrieval


class AgentContextConfig(BaseModel):
  """Configuration settings for building the agent context retrieval system.

  Attributes:
    retrieval: Configuration for the underlying lexical search and matching engine.
    archive_manifest_path: Path to the CSV file containing the downloaded/archived
      document registry, used for resolving local file paths from URLs.
    default_limit: Default maximum number of context hits to return if not overridden.
  """
  retrieval: RetrievalConfig = RetrievalConfig()
  archive_manifest_path: Path = Path("manifests/archive_manifest.csv")
  default_limit: int = 5


class AgentCitation(BaseModel):
  """Provenance citation mapping a context hit back to its original source.

  Attributes:
    source_url: The original web URL of the document or page where the information was found.
    source_document: The local path to the archived copy of the source document.
    page: The specific page number within the document, if the source is a paginated PDF.
    variable_url: The original URL of the variable detail page, if this record is a variable.
    variable_document: The local path to the archived copy of the variable detail page.
  """
  source_url: str
  source_document: str = ""
  page: int | None = None
  variable_url: str = ""
  variable_document: str = ""


class AgentContextHit(BaseModel):
  """A single matched record from the CMS Knowledge Base retrieval system.

  Attributes:
    record_id: Unique identifier for the matched entity.
    record_type: Type of the entity (e.g., 'dataset', 'document', 'variable', 'chunk').
    title: Human-readable name or title of the matched record.
    dataset_id: The ID of the dataset this record belongs to or is associated with.
    score: The lexical matching score indicating relevance to the query.
    snippet: A short text excerpt showing the context around the query match.
    citation: Provenance tracking details linking back to the raw source documents.
  """
  record_id: str
  record_type: str
  title: str
  dataset_id: str
  score: float
  snippet: str
  citation: AgentCitation


class AgentContextResponse(BaseModel):
  """The structured response payload returned to downstream LLM agents.

  Attributes:
    query: The original search query string that was processed.
    results: List of matching context hits, ordered by relevance/score.
  """
  query: str
  results: list[AgentContextHit]


class _VariableLinkParser(HTMLParser):
  """A lightweight HTML parser designed to extract variable page URLs from tables.

  At ResDAC, data documentation pages listing variables display them in a tabular
  format. For a given row, one cell contains the variable name, and another cell
  often contains a link to the detail page (under `/cms-data/variables/`).
  This parser builds a representation of the table rows and cells along with their
  hyperlinks so we can resolve the exact variable URL.
  """

  def __init__(self) -> None:
    super().__init__()
    # Store rows, where each row is a list of cell data: (cell_text, link_href)
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


def read_archived_document_map(input_path: Path) -> dict[str, str]:
  """Reads the archive manifest and builds a mapping of URLs to local file paths.

  This mapping is crucial for downstream components to locate the offline files
  associated with any ResDAC page or asset URL.

  Args:
    input_path: Path to the `archive_manifest.csv` file.

  Returns:
    A dictionary mapping clean web URLs to their corresponding local archived paths.
    Only successfully archived entries are returned; failed, deferred, or skipped
    downloads are omitted from the map.
  """
  if not input_path.is_file():
    return {}

  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      return {}
    required = {"url", "archive_state", "local_path"}
    if not required.issubset(set(reader.fieldnames)):
      return {}
    return {
      row["url"].strip(): row["local_path"].strip()
      for row in reader
      if row.get("archive_state") == "archived"
      and row.get("url", "").strip()
      and row.get("local_path", "").strip()
    }


def _find_variable_link(
  result: SearchResult,
  archived_documents_by_url: dict[str, str] | None = None,
) -> tuple[str, str]:
  """Locates the original detail page URL and local archived file for a variable.

  If the retrieved search result is a variable, its source document might be a
  general dataset documentation page (which lists multiple variables in a table).
  To provide an exact citation, this function parses that page's HTML to locate
  the specific hyperlink pointing to the individual variable's detail page.

  Args:
    result: The search result match representing a variable or chunk.
    archived_documents_by_url: A dictionary mapping URLs to local file paths,
      loaded from the archive manifest.

  Returns:
    A tuple of (variable_url, variable_document_path).
    Both are empty strings if the variable link cannot be resolved, or if the
    record type is not a variable.
  """
  source_document = Path(result.source_document)
  if source_document.parts and source_document.parts[0] == "data":
    pkg_subpath = Path(*source_document.parts[1:])
    resolved_path = get_packaged_data_path(str(pkg_subpath))
    if resolved_path.is_file():
      source_document = resolved_path

  if result.record_type != "variable" or not source_document.is_file():
    return "", ""

  # If the source URL itself is already pointing to a variable page, return it directly.
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
    # Verify if the target variable's title matches one of the cells in the table row.
    if result.title not in cell_texts:
      continue
    # Locate a cell with a link pointing to the variable detail endpoint.
    for _, href in row:
      if "/cms-data/variables/" in href:
        variable_url = urljoin("https://resdac.org", href)
        variable_document = (archived_documents_by_url or {}).get(variable_url, "")
        return variable_url, variable_document
  return "", ""


def context_hit_from_search_result(
  result: SearchResult,
  archived_documents_by_url: dict[str, str] | None = None,
) -> AgentContextHit:
  """Converts a low-level SearchResult into a high-level AgentContextHit.

  This encapsulates resolving variable details and mapping the result attributes
  to the standard schema expected by downstream LLM agents.

  Args:
    result: The raw lexical search match.
    archived_documents_by_url: Mapping of URLs to local paths for resolving
      the variable's individual detail page.

  Returns:
    An AgentContextHit with populated citations and provenance.
  """
  variable_url, variable_document = _find_variable_link(
    result, archived_documents_by_url
  )
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
  """Performs search retrieval and constructs a citation-backed context response.

  This is the primary programmatic entry point for the agent context API.

  Args:
    config: Configuration parameters, including retrieval paths and limits.
    query: The search query string.
    limit: Optional override for the maximum number of hits to return.

  Returns:
    An AgentContextResponse containing the matches and their provenance citations.
  """
  resolved_limit = config.default_limit if limit is None else limit
  results = run_retrieval(config.retrieval, query, resolved_limit)
  archived_documents_by_url = read_archived_document_map(config.archive_manifest_path)
  return AgentContextResponse(
    query=query,
    results=[
      context_hit_from_search_result(result, archived_documents_by_url)
      for result in results
    ],
  )


def build_arg_parser() -> argparse.ArgumentParser:
  """Constructs the command-line argument parser for the agent context CLI.

  Returns:
    An ArgumentParser instance configured with path and query overrides.
  """
  parser = argparse.ArgumentParser(
    description="Return citation-preserving CMS KB context for agent workflows."
  )
  parser.add_argument("--query", required=True)
  parser.add_argument("--limit", type=int, default=5)
  parser.add_argument(
    "--datasets-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/datasets.csv"),
  )
  parser.add_argument(
    "--documents-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/documents.csv"),
  )
  parser.add_argument(
    "--variables-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/variables.csv"),
  )
  parser.add_argument(
    "--chunks-jsonl",
    type=Path,
    default=get_packaged_data_path("parsed/chunks.jsonl"),
  )
  parser.add_argument(
    "--archive-manifest",
    type=Path,
    default=Path("manifests/archive_manifest.csv"),
  )
  parser.add_argument(
    "--database-path",
    type=Path,
    default=get_packaged_data_path("index/retrieval.sqlite"),
  )
  parser.add_argument("--json", action="store_true", help="Emit JSON output.")
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI execution entrypoint for retrieving agent context.

  Args:
    argv: List of command-line arguments. If None, uses sys.argv.

  Returns:
    An integer exit code (0 for success, 1 for failure).
  """
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = AgentContextConfig(
    retrieval=RetrievalConfig(
      datasets_metadata_path=args.datasets_metadata,
      documents_metadata_path=args.documents_metadata,
      variables_metadata_path=args.variables_metadata,
      chunks_jsonl_path=args.chunks_jsonl,
      database_path=args.database_path,
    ),
    archive_manifest_path=args.archive_manifest,
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
  "read_archived_document_map",
]
