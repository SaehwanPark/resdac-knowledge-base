"""Phase 6 variable-level metadata extraction from parsed CMS KB chunks.

This module implements Phase 6 (Variable-Level Metadata Extraction) of the pipeline.
It scans parsed text chunks (`chunks.jsonl`) for occurrences of variable names and uses regex/text heuristics
to extract definitions, aliases, and active years. It also parses archived ResDAC variable-detail
HTML pages (`/cms-data/variables/...`) to build a canonical variable catalog.

Key Architecture Details:
- Text-Based Extraction: Inspects text chunks to find lines matching variable patterns
  (e.g., table layouts or paragraph headers), pulling out definitions and active years.
- Canonical Variable Parsing: Parses raw archived HTML of variable detail pages (via `_VariablePageParser`)
  to capture the variable label, description table, and membership in different datasets.
- Priority Deduplication: Resolves conflicting definitions of the same variable name using priorities
  (e.g. favoring details extracted from HTML pages over general PDF/spreadsheet chunks).
- Handoff Summary: Outputs CSV registries and edges, writing `_workspace/07_variable_pack.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Sequence, TypeVar
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

from .archive import ArchiveManifestRow
from .extraction import read_archive_manifest_csv
from .parsing import ChunkMetadata
from .paths import get_packaged_data_path

VariableFieldnames = Literal[
  "variable_id",
  "variable_name",
  "dataset_id",
  "definition",
  "aliases",
  "years",
  "source_document",
  "source_url",
  "page",
  "chunk_id",
  "extraction_notes",
]
VariableEdgeFieldnames = Literal[
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "page",
  "chunk_id",
]
CanonicalVariableFieldnames = Literal[
  "variable_id",
  "variable_name",
  "variable_label",
  "definition",
  "source",
  "source_url",
  "source_document",
  "extraction_notes",
]
DataSourceVariableEdgeFieldnames = Literal[
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "variable_url",
  "variable_document",
  "evidence_type",
  "page",
  "chunk_id",
]

VARIABLE_FIELDNAMES: list[VariableFieldnames] = [
  "variable_id",
  "variable_name",
  "dataset_id",
  "definition",
  "aliases",
  "years",
  "source_document",
  "source_url",
  "page",
  "chunk_id",
  "extraction_notes",
]
VARIABLE_EDGE_FIELDNAMES: list[VariableEdgeFieldnames] = [
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "page",
  "chunk_id",
]
CANONICAL_VARIABLE_FIELDNAMES: list[CanonicalVariableFieldnames] = [
  "variable_id",
  "variable_name",
  "variable_label",
  "definition",
  "source",
  "source_url",
  "source_document",
  "extraction_notes",
]
DATA_SOURCE_VARIABLE_EDGE_FIELDNAMES: list[DataSourceVariableEdgeFieldnames] = [
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "variable_url",
  "variable_document",
  "evidence_type",
  "page",
  "chunk_id",
]

VARIABLE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:_[A-Z0-9]+)+\b")
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DEFINITION_SEPARATOR_PATTERN = re.compile(r"\s+(?:[-:–—]|=)\s+")
ALIAS_PATTERN = re.compile(
  r"\b(?:also known as|aka|alias(?:es)?|formerly)\b[:\s]+([^.;\n]+)",
  re.IGNORECASE,
)
TABLE_SEPARATOR_CELL_PATTERN = re.compile(r"^:?-{2,}:?$")


class VariableExtractionConfig(BaseModel):
  chunks_jsonl_path: Path = Field(default_factory=lambda: get_packaged_data_path("parsed/chunks.jsonl"))
  archive_manifest_path: Path = Path("manifests/archive_manifest.csv")
  metadata_dir: Path = Path("data/metadata")
  graph_dir: Path = Path("data/graph")
  workspace_dir: Path = Path("_workspace")


class VariableMetadataRow(BaseModel):
  variable_id: str
  variable_name: str
  dataset_id: str
  definition: str
  aliases: str = ""
  years: str = ""
  source_document: str
  source_url: str
  page: int | None = None
  chunk_id: str
  extraction_notes: str = ""


class VariableEdgeRow(BaseModel):
  source_id: str
  target_id: str
  relationship: str = "contains"
  source_url: str
  source_document: str
  page: int | None = None
  chunk_id: str


class CanonicalVariableRow(BaseModel):
  variable_id: str
  variable_name: str = ""
  variable_label: str = ""
  definition: str = ""
  source: str = "resdac_variable_page"
  source_url: str
  source_document: str
  extraction_notes: str = ""


class DataSourceVariableEdgeRow(BaseModel):
  source_id: str
  target_id: str
  relationship: str = "contains"
  source_url: str
  source_document: str = ""
  variable_url: str
  variable_document: str
  evidence_type: str = "variable_page_containing_file"
  page: int | None = None
  chunk_id: str = ""


class VariableExtractionFailure(BaseModel):
  chunk_id: str = ""
  source_document: str = ""
  reason: str


class VariableExtractionResult(BaseModel):
  config: VariableExtractionConfig
  chunks_read: int = 0
  variables: list[VariableMetadataRow] = Field(default_factory=list)
  edges: list[VariableEdgeRow] = Field(default_factory=list)
  canonical_variables: list[CanonicalVariableRow] = Field(default_factory=list)
  data_source_variable_edges: list[DataSourceVariableEdgeRow] = Field(default_factory=list)
  skipped_candidates: int = 0
  failures: list[VariableExtractionFailure] = Field(default_factory=list)

  @property
  def variable_count(self) -> int:
    return len(self.variables)

  @property
  def edge_count(self) -> int:
    return len(self.edges)

  @property
  def canonical_variable_count(self) -> int:
    return len(self.canonical_variables)

  @property
  def data_source_variable_edge_count(self) -> int:
    return len(self.data_source_variable_edges)

  @property
  def failure_count(self) -> int:
    return len(self.failures)


def _slugify(value: str) -> str:
  slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
  return slug or "unknown"


def _stable_variable_id(dataset_id: str, variable_name: str) -> str:
  return f"{_slugify(dataset_id)}__var__{_slugify(variable_name)}"


def _canonical_variable_id_from_url(url: str) -> str:
  slug = Path(urlparse(url).path).name
  return _slugify(slug)


def _dataset_id_from_resdac_file_url(url: str) -> str | None:
  parts = [part for part in urlparse(url).path.split("/") if part]
  if len(parts) < 3 or parts[0] != "cms-data" or parts[1] != "files":
    return None
  return _slugify(parts[2])


def _clean_definition(value: str) -> str:
  cleaned = re.sub(r"\s+", " ", value).strip(" .;:-–—")
  return cleaned


class _VariablePageParser(HTMLParser):
  def __init__(self, page_url: str) -> None:
    super().__init__()
    self.page_url = page_url
    self.title_parts: list[str] = []
    self.h1_parts: list[str] = []
    self.links: list[tuple[str, str]] = []
    self.rows: list[list[str]] = []
    self._in_title = False
    self._in_h1 = False
    self._in_a = False
    self._current_href = ""
    self._current_link_text: list[str] = []
    self._current_row: list[str] | None = None
    self._current_cell: list[str] | None = None

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    attributes = dict(attrs)
    if tag == "title":
      self._in_title = True
    elif tag == "h1" and not self.h1_parts:
      self._in_h1 = True
    elif tag == "a":
      href = attributes.get("href")
      if href:
        self._in_a = True
        self._current_href = href
        self._current_link_text = []
    elif tag == "tr":
      self._current_row = []
    elif tag in {"td", "th"} and self._current_row is not None:
      self._current_cell = []

  def handle_data(self, data: str) -> None:
    if self._in_title:
      self.title_parts.append(data)
    if self._in_h1:
      self.h1_parts.append(data)
    if self._in_a:
      self._current_link_text.append(data)
    if self._current_cell is not None:
      self._current_cell.append(data)

  def handle_endtag(self, tag: str) -> None:
    if tag == "title":
      self._in_title = False
    elif tag == "h1":
      self._in_h1 = False
    elif tag == "a" and self._in_a:
      self.links.append((
        urljoin(self.page_url, self._current_href),
        re.sub(r"\s+", " ", "".join(self._current_link_text)).strip(),
      ))
      self._in_a = False
      self._current_href = ""
      self._current_link_text = []
    elif tag in {"td", "th"} and self._current_row is not None:
      text = re.sub(r"\s+", " ", "".join(self._current_cell or [])).strip()
      self._current_row.append(text)
      self._current_cell = None
    elif tag == "tr" and self._current_row is not None:
      if self._current_row:
        self.rows.append(self._current_row)
      self._current_row = None

  @property
  def title(self) -> str:
    value = re.sub(r"\s+", " ", "".join(self.h1_parts)).strip()
    if not value:
      value = re.sub(r"\s+", " ", "".join(self.title_parts)).strip()
    return value.removesuffix(" | ResDAC").strip()


def _field_value_from_rows(rows: list[list[str]], names: set[str]) -> str:
  for row in rows:
    if len(row) < 2:
      continue
    label = row[0].strip(" :").lower()
    if label in names:
      return row[1].strip()
  return ""


def _definition_from_text(text: str, variable_name: str) -> str:
  patterns = [
    r"(?:Definition|Description)\s*[:\-]\s*(.+)",
    rf"{re.escape(variable_name)}\s*(?:[-:=])\s*(.+)",
  ]
  for pattern in patterns:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is not None:
      return _clean_definition(match.group(1).splitlines()[0])
  return ""


def _extract_canonical_variable_from_page(
  row: ArchiveManifestRow,
) -> tuple[CanonicalVariableRow | None, list[DataSourceVariableEdgeRow]]:
  if row.archive_state != "archived" or row.resource_kind != "variable_page":
    return None, []
  if not row.local_path or not Path(row.local_path).is_file():
    return None, []

  html = Path(row.local_path).read_text(encoding="utf-8", errors="replace")
  parser = _VariablePageParser(row.url)
  parser.feed(html)
  page_text = re.sub(r"<[^>]+>", " ", html)
  page_text = re.sub(r"\s+", " ", page_text)
  variable_name = _field_value_from_rows(
    parser.rows,
    {"sas name", "variable name", "name"},
  )
  if not variable_name:
    match = re.search(r"\b[A-Z][A-Z0-9]{1,}(?:_[A-Z0-9]+)+\b", html)
    variable_name = match.group(0) if match is not None else ""
  definition = _field_value_from_rows(
    parser.rows,
    {"definition", "description"},
  )
  if not definition and variable_name:
    definition = _definition_from_text(page_text, variable_name)

  variable = CanonicalVariableRow(
    variable_id=_canonical_variable_id_from_url(row.url),
    variable_name=variable_name,
    variable_label=parser.title,
    definition=definition,
    source_url=row.url,
    source_document=row.local_path,
    extraction_notes="" if variable_name else "variable name not found on page",
  )

  edges: dict[str, DataSourceVariableEdgeRow] = {}
  for href, _text in parser.links:
    source_id = _dataset_id_from_resdac_file_url(href)
    if source_id is None:
      continue
    edges[href] = DataSourceVariableEdgeRow(
      source_id=source_id,
      target_id=variable.variable_id,
      source_url=href,
      variable_url=row.url,
      variable_document=row.local_path,
    )
  return variable, sorted(edges.values(), key=lambda edge: edge.source_url)


def _extract_canonical_variables_from_manifest(
  manifest_path: Path,
) -> tuple[list[CanonicalVariableRow], list[DataSourceVariableEdgeRow], list[VariableExtractionFailure]]:
  if not manifest_path.is_file():
    return [], [], []
  failures: list[VariableExtractionFailure] = []
  try:
    manifest_rows = read_archive_manifest_csv(manifest_path)
  except Exception as exc:
    return [], [], [
      VariableExtractionFailure(reason=f"failed to read archive manifest: {exc}")
    ]

  variables_by_id: dict[str, CanonicalVariableRow] = {}
  edges_by_key: dict[tuple[str, str, str], DataSourceVariableEdgeRow] = {}
  for manifest_row in manifest_rows:
    try:
      variable, edges = _extract_canonical_variable_from_page(manifest_row)
    except Exception as exc:
      failures.append(
        VariableExtractionFailure(
          source_document=manifest_row.local_path,
          reason=f"failed to extract canonical variable page: {exc}",
        )
      )
      continue
    if variable is None:
      continue
    variables_by_id[variable.variable_id] = variable
    for edge in edges:
      edges_by_key[(edge.source_id, edge.target_id, edge.source_url)] = edge

  return (
    sorted(variables_by_id.values(), key=lambda variable: variable.variable_id),
    sorted(edges_by_key.values(), key=lambda edge: (edge.source_id, edge.target_id)),
    failures,
  )


def _table_cells(line: str) -> list[str]:
  if "|" not in line:
    return []
  cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
  return [cell for cell in cells if cell]


def _candidate_table_definition(line: str, variable_name: str) -> str | None:
  cells = _table_cells(line)
  if len(cells) < 2:
    return None
  if all(TABLE_SEPARATOR_CELL_PATTERN.fullmatch(cell) is not None for cell in cells):
    return None

  for index, cell in enumerate(cells):
    if cell != variable_name:
      continue
    for candidate in cells[index + 1:]:
      if candidate == variable_name:
        continue
      if TABLE_SEPARATOR_CELL_PATTERN.fullmatch(candidate) is not None:
        continue
      if candidate.lower() in {"variable name", "sas name", "short name", "long name"}:
        continue
      definition = _clean_definition(candidate)
      if definition:
        return definition
  return None


def _candidate_definition(line: str, variable_name: str) -> str | None:
  table_definition = _candidate_table_definition(line, variable_name)
  if table_definition is not None:
    return table_definition

  match = re.search(rf"\b{re.escape(variable_name)}\b", line)
  if match is None:
    return None

  after = line[match.end():].strip()
  if not after:
    return None

  separator_match = DEFINITION_SEPARATOR_PATTERN.match(f" {after}")
  if separator_match is not None:
    definition = after[separator_match.end() - 1:]
    return _clean_definition(definition)

  lower_after = after.lower()
  for prefix in ("means ", "indicates ", "identifies ", "is "):
    if lower_after.startswith(prefix):
      return _clean_definition(after[len(prefix):])

  return None


def _extract_aliases(line: str) -> str:
  aliases: set[str] = set()
  for match in ALIAS_PATTERN.finditer(line):
    for raw_alias in re.split(r",|\bor\b", match.group(1)):
      alias = raw_alias.strip(" .;()")
      if alias and YEAR_PATTERN.fullmatch(alias) is None:
        aliases.add(alias)
  return "|".join(sorted(aliases))


def _extract_years(line: str) -> str:
  return "|".join(sorted(set(YEAR_PATTERN.findall(line))))


def _source_priority(row: VariableMetadataRow) -> int:
  source_url = row.source_url.lower()
  source_document = row.source_document.lower()
  is_html = source_document.endswith(".html") or "text/html" in row.extraction_notes.lower()

  if is_html and "/data-documentation" in source_url:
    return 0
  if is_html:
    return 1
  if source_document.endswith(".xlsx") or source_url.endswith(".xlsx"):
    return 2
  return 3


def extract_variables_from_chunk(
  chunk: ChunkMetadata,
) -> tuple[list[VariableMetadataRow], int]:
  rows: list[VariableMetadataRow] = []
  skipped_candidates = 0
  seen_in_chunk: set[str] = set()

  for raw_line in chunk.text.splitlines():
    line = re.sub(r"\s+", " ", raw_line).strip()
    if not line:
      continue
    for variable_name in sorted(set(VARIABLE_PATTERN.findall(line))):
      if variable_name in seen_in_chunk:
        continue
      seen_in_chunk.add(variable_name)
      definition = _candidate_definition(line, variable_name)
      if definition is None:
        skipped_candidates += 1
        continue
      rows.append(
        VariableMetadataRow(
          variable_id=_stable_variable_id(chunk.dataset, variable_name),
          variable_name=variable_name,
          dataset_id=chunk.dataset,
          definition=definition,
          aliases=_extract_aliases(line),
          years=_extract_years(line),
          source_document=chunk.source_document,
          source_url=chunk.url,
          page=chunk.page,
          chunk_id=chunk.chunk_id,
        )
      )

  return rows, skipped_candidates


def read_chunks_jsonl(input_path: Path) -> tuple[list[ChunkMetadata], list[VariableExtractionFailure]]:
  chunks: list[ChunkMetadata] = []
  failures: list[VariableExtractionFailure] = []
  with input_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
      if not line.strip():
        continue
      try:
        payload = json.loads(line)
        chunks.append(ChunkMetadata.model_validate(payload))
      except Exception as exc:
        failures.append(
          VariableExtractionFailure(
            chunk_id=f"line-{line_number}",
            reason=f"failed to parse chunk JSON: {exc}",
          )
        )
  return chunks, failures


def _deduplicate_variables(
  rows: list[VariableMetadataRow],
) -> list[VariableMetadataRow]:
  unique: dict[str, VariableMetadataRow] = {}
  for row in rows:
    existing = unique.get(row.variable_id)
    if existing is None:
      unique[row.variable_id] = row
      continue
    row_priority = _source_priority(row)
    existing_priority = _source_priority(existing)
    if row_priority < existing_priority:
      unique[row.variable_id] = row
      continue
    if row_priority == existing_priority and len(row.definition) > len(existing.definition):
      unique[row.variable_id] = row
  return sorted(unique.values(), key=lambda row: (row.dataset_id, row.variable_name))


def _edge_for_variable(row: VariableMetadataRow) -> VariableEdgeRow:
  return VariableEdgeRow(
    source_id=row.dataset_id,
    target_id=row.variable_id,
    source_url=row.source_url,
    source_document=row.source_document,
    page=row.page,
    chunk_id=row.chunk_id,
  )


_T = TypeVar("_T", bound=BaseModel)


def _write_model_csv(
  rows: list[_T], output_path: Path, fieldnames: Sequence[str]
) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      writer.writerow(row.model_dump())


def write_variable_outputs(result: VariableExtractionResult) -> None:
  _write_model_csv(
    result.variables,
    result.config.metadata_dir / "variables.csv",
    VARIABLE_FIELDNAMES,
  )
  _write_model_csv(
    result.edges,
    result.config.graph_dir / "variable_edges.csv",
    VARIABLE_EDGE_FIELDNAMES,
  )
  _write_model_csv(
    result.canonical_variables,
    result.config.metadata_dir / "canonical_variables.csv",
    CANONICAL_VARIABLE_FIELDNAMES,
  )
  _write_model_csv(
    result.data_source_variable_edges,
    result.config.graph_dir / "data_source_variable_edges.csv",
    DATA_SOURCE_VARIABLE_EDGE_FIELDNAMES,
  )


def write_variable_workspace_summary(result: VariableExtractionResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "07_variable_pack.md"
  lines = [
    "# Variable Pack",
    "",
    f"- Parsed chunks input: {result.config.chunks_jsonl_path}",
    f"- Chunks read: {result.chunks_read}",
    f"- Variables: {result.variable_count}",
    f"- Variable edges: {result.edge_count}",
    f"- Canonical variables: {result.canonical_variable_count}",
    f"- Data source variable edges: {result.data_source_variable_edge_count}",
    f"- Skipped candidates: {result.skipped_candidates}",
    f"- Failures: {result.failure_count}",
    "",
    "## Outputs",
    "",
    f"- Variable metadata: {result.config.metadata_dir / 'variables.csv'}",
    f"- Variable graph edges: {result.config.graph_dir / 'variable_edges.csv'}",
    f"- Canonical variable metadata: {result.config.metadata_dir / 'canonical_variables.csv'}",
    f"- Data source variable graph edges: {result.config.graph_dir / 'data_source_variable_edges.csv'}",
    "",
    "## Failures",
    "",
  ]
  if result.failures:
    lines.extend(["| chunk_id | source_document | reason |", "| --- | --- | --- |"])
    for failure in result.failures[:25]:
      reason_safe = failure.reason.replace("|", "\\|").replace("\n", " ")
      lines.append(
        f"| {failure.chunk_id} | {failure.source_document} | {reason_safe} |"
      )
    if len(result.failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(result.failures) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def _resolve_variable_citations(
  variables: list[VariableMetadataRow],
  canonical_variables: list[CanonicalVariableRow],
  data_source_variable_edges: list[DataSourceVariableEdgeRow],
) -> None:
  """Resolves extracted variable source URLs and documents to their canonical detail pages.

  Updates the variables list in-place where matches are found in the data source edges.
  """
  canonical_id_to_name = {
    v.variable_id: v.variable_name
    for v in canonical_variables
    if v.variable_name
  }
  resolved_vars: dict[tuple[str, str], tuple[str, str]] = {}
  for edge in data_source_variable_edges:
    var_name = canonical_id_to_name.get(edge.target_id)
    if var_name:
      resolved_vars[(edge.source_id.lower(), var_name.lower())] = (
        edge.variable_url,
        edge.variable_document,
      )

  for row in variables:
    lookup_key = (row.dataset_id.lower(), row.variable_name.lower())
    if lookup_key in resolved_vars:
      var_url, var_doc = resolved_vars[lookup_key]
      if var_url:
        row.source_url = var_url
      if var_doc:
        row.source_document = var_doc


def run_variable_extraction(
  config: VariableExtractionConfig,
) -> tuple[VariableExtractionResult, Path]:
  """Performs Phase 6 variable-level metadata and relationship extraction.

  Parses text definitions from chunks and parses canonical variables from HTML pages,
  deduplicating matches and writing the output CSV catalogs.

  Args:
    config: VariableExtractionConfig configuration parameters.

  Returns:
    A tuple of (VariableExtractionResult, variable_report_path).
  """
  chunks, failures = read_chunks_jsonl(config.chunks_jsonl_path)
  canonical_variables, data_source_variable_edges, canonical_failures = (
    _extract_canonical_variables_from_manifest(config.archive_manifest_path)
  )
  failures.extend(canonical_failures)
  extracted_rows: list[VariableMetadataRow] = []
  skipped_candidates = 0

  for chunk in chunks:
    source_document = Path(chunk.source_document)
    if not chunk.source_document.strip():
      failures.append(
        VariableExtractionFailure(
          chunk_id=chunk.chunk_id,
          reason="chunk has empty source_document",
        )
      )
      continue
    if not source_document.is_file():
      failures.append(
        VariableExtractionFailure(
          chunk_id=chunk.chunk_id,
          source_document=chunk.source_document,
          reason="source_document does not exist locally",
        )
      )
      continue
    rows, skipped = extract_variables_from_chunk(chunk)
    extracted_rows.extend(rows)
    skipped_candidates += skipped

  variables = _deduplicate_variables(extracted_rows)
  _resolve_variable_citations(
    variables, canonical_variables, data_source_variable_edges
  )
  result = VariableExtractionResult(
    config=config,
    chunks_read=len(chunks),
    variables=variables,
    edges=[_edge_for_variable(row) for row in variables],
    canonical_variables=canonical_variables,
    data_source_variable_edges=data_source_variable_edges,
    skipped_candidates=skipped_candidates,
    failures=failures,
  )
  write_variable_outputs(result)
  summary_path = write_variable_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Extract variable-level metadata from parsed CMS KB chunks."
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
  parser.add_argument("--metadata-dir", type=Path, default=Path("data/metadata"))
  parser.add_argument("--graph-dir", type=Path, default=Path("data/graph"))
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = VariableExtractionConfig(
    chunks_jsonl_path=args.chunks_jsonl,
    archive_manifest_path=args.archive_manifest,
    metadata_dir=args.metadata_dir,
    graph_dir=args.graph_dir,
    workspace_dir=args.workspace_dir,
  )
  try:
    result, summary_path = run_variable_extraction(config)
    print(
      f"wrote {result.variable_count} variables and {result.edge_count} "
      f"variable edges; wrote {result.canonical_variable_count} canonical "
      f"variables and {result.data_source_variable_edge_count} data source "
      f"variable edges; summary: {summary_path}"
    )
    return 1 if result.failure_count else 0
  except Exception as exc:
    print(f"Error executing variable extraction: {exc}", file=sys.stderr)
    return 1


__all__ = [
  "VARIABLE_EDGE_FIELDNAMES",
  "VARIABLE_FIELDNAMES",
  "CANONICAL_VARIABLE_FIELDNAMES",
  "DATA_SOURCE_VARIABLE_EDGE_FIELDNAMES",
  "CanonicalVariableRow",
  "DataSourceVariableEdgeRow",
  "VariableEdgeRow",
  "VariableExtractionConfig",
  "VariableExtractionFailure",
  "VariableExtractionResult",
  "VariableMetadataRow",
  "build_arg_parser",
  "extract_variables_from_chunk",
  "main",
  "read_chunks_jsonl",
  "run_variable_extraction",
  "write_variable_outputs",
  "write_variable_workspace_summary",
]
