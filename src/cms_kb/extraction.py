"""Phase 2 metadata extraction from archived CMS KB materials."""

from __future__ import annotations

import argparse
import csv
import hashlib
from html.parser import HTMLParser
import re
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .archive import ARCHIVE_MANIFEST_FIELDNAMES, ArchiveManifestRow
from .inventory import ResourceKind, normalize_url, parse_page

DatasetFieldnames = Literal[
  "dataset_id",
  "name",
  "program",
  "category",
  "availability",
  "source_url",
  "local_path",
  "sha256",
  "extraction_notes",
]
DocumentFieldnames = Literal[
  "document_id",
  "dataset_id",
  "title",
  "document_kind",
  "source_url",
  "local_path",
  "sha256",
  "content_type",
  "extraction_notes",
]
DocumentEdgeFieldnames = Literal[
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "local_path",
  "sha256",
]
OntologyNodeFieldnames = Literal[
  "node_id",
  "node_class",
  "name",
  "source_url",
  "local_path",
  "sha256",
]
OntologyEdgeFieldnames = Literal[
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "local_path",
  "sha256",
]

DATASET_FIELDNAMES: list[DatasetFieldnames] = [
  "dataset_id",
  "name",
  "program",
  "category",
  "availability",
  "source_url",
  "local_path",
  "sha256",
  "extraction_notes",
]
DOCUMENT_FIELDNAMES: list[DocumentFieldnames] = [
  "document_id",
  "dataset_id",
  "title",
  "document_kind",
  "source_url",
  "local_path",
  "sha256",
  "content_type",
  "extraction_notes",
]
DOCUMENT_EDGE_FIELDNAMES: list[DocumentEdgeFieldnames] = [
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "local_path",
  "sha256",
]
ONTOLOGY_NODE_FIELDNAMES: list[OntologyNodeFieldnames] = [
  "node_id",
  "node_class",
  "name",
  "source_url",
  "local_path",
  "sha256",
]
ONTOLOGY_EDGE_FIELDNAMES: list[OntologyEdgeFieldnames] = [
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "local_path",
  "sha256",
]

EXTRACTABLE_RESOURCE_KINDS: tuple[ResourceKind, ...] = (
  "dataset_page",
  "documentation_page",
  "asset",
)


class ExtractionConfig(BaseModel):
  archive_manifest_path: Path = Path("manifests/archive_manifest.csv")
  metadata_dir: Path = Path("data/metadata")
  graph_dir: Path = Path("data/graph")
  workspace_dir: Path = Path("_workspace")


class DatasetMetadataRow(BaseModel):
  dataset_id: str
  name: str = ""
  program: str = ""
  category: str = ""
  availability: str = ""
  source_url: str
  local_path: str
  sha256: str
  extraction_notes: str = ""


class DocumentMetadataRow(BaseModel):
  document_id: str
  dataset_id: str
  title: str = ""
  document_kind: str
  source_url: str
  local_path: str
  sha256: str
  content_type: str = ""
  extraction_notes: str = ""


class DocumentEdgeRow(BaseModel):
  source_id: str
  target_id: str
  relationship: str = "has_document"
  source_url: str
  local_path: str
  sha256: str


class OntologyNodeRow(BaseModel):
  node_id: str
  node_class: str  # "Dataset", "Table", "Variable", "Program"
  name: str
  source_url: str
  local_path: str
  sha256: str


class OntologyEdgeRow(BaseModel):
  source_id: str
  target_id: str
  relationship: str
  source_url: str
  local_path: str
  sha256: str


class ExtractionFailure(BaseModel):
  url: str
  resource_kind: ResourceKind
  local_path: str = ""
  reason: str


class ExtractionResult(BaseModel):
  config: ExtractionConfig
  manifest_rows: int
  datasets: list[DatasetMetadataRow] = Field(default_factory=list)
  documents: list[DocumentMetadataRow] = Field(default_factory=list)
  document_edges: list[DocumentEdgeRow] = Field(default_factory=list)
  ontology_nodes: list[OntologyNodeRow] = Field(default_factory=list)
  ontology_edges: list[OntologyEdgeRow] = Field(default_factory=list)
  failures: list[ExtractionFailure] = Field(default_factory=list)

  @property
  def dataset_count(self) -> int:
    return len(self.datasets)

  @property
  def document_count(self) -> int:
    return len(self.documents)

  @property
  def edge_count(self) -> int:
    return len(self.document_edges)

  @property
  def ontology_node_count(self) -> int:
    return len(self.ontology_nodes)

  @property
  def ontology_edge_count(self) -> int:
    return len(self.ontology_edges)

  @property
  def failure_count(self) -> int:
    return len(self.failures)


def read_archive_manifest_csv(input_path: Path) -> list[ArchiveManifestRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"archive manifest CSV has no header: {input_path}")

    missing_fieldnames = [
      fieldname
      for fieldname in ARCHIVE_MANIFEST_FIELDNAMES
      if fieldname not in reader.fieldnames
    ]
    if missing_fieldnames:
      raise ValueError(
        "archive manifest CSV is missing required columns: "
        f"{', '.join(missing_fieldnames)}"
      )

    rows: list[ArchiveManifestRow] = []
    for raw_row in reader:
      normalized_row = {
        "url": raw_row["url"],
        "resource_kind": raw_row["resource_kind"],
        "asset_kind": raw_row["asset_kind"],
        "source_url": raw_row["source_url"],
        "source_title": raw_row["source_title"],
        "content_type": raw_row["content_type"],
        "http_status": (
          int(raw_row["http_status"]) if raw_row["http_status"].strip() else None
        ),
        "archive_state": raw_row["archive_state"],
        "downloaded_at_utc": raw_row["downloaded_at_utc"],
        "sha256": raw_row["sha256"],
        "local_path": raw_row["local_path"],
        "error": raw_row["error"],
      }
      rows.append(ArchiveManifestRow.model_validate(normalized_row))
  return rows


def _slugify(value: str) -> str:
  slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
  return slug or "unknown"


def _dataset_id_from_url(url: str) -> str:
  dataset_id = _dataset_id_from_resdac_file_url(url)
  if dataset_id is not None:
    return dataset_id
  return _slugify(Path(urlparse(url).path).stem)


def _dataset_id_from_resdac_file_url(url: str) -> str | None:
  parts = [part for part in urlparse(url).path.split("/") if part]
  if "files" not in parts:
    return None
  files_index = parts.index("files")
  if files_index + 1 >= len(parts):
    return None
  return _slugify(parts[files_index + 1])


def _document_suffix_from_url(url: str) -> str:
  path = urlparse(url).path
  path_parts = [part for part in path.split("/") if part]
  if path.endswith("/data-documentation") or path_parts[-1:] == ["data-documentation"]:
    return "data-documentation"
  path_name = Path(path).name
  if not path_name:
    return "document"
  suffix = Path(path_name).suffix.lower().lstrip(".")
  stem = _slugify(Path(path_name).stem)
  if suffix:
    return f"{stem}_{_slugify(suffix)}"
  return stem


def _read_html_title(local_path: Path) -> str:
  html = local_path.read_text(encoding="utf-8", errors="replace")
  title, _ = parse_page(html)
  return title


def _verify_archived_row(row: ArchiveManifestRow) -> ExtractionFailure | None:
  if not row.local_path:
    return ExtractionFailure(
      url=row.url,
      resource_kind=row.resource_kind,
      reason="archived row has no local path",
    )
  local_path = Path(row.local_path)
  if not local_path.exists():
    return ExtractionFailure(
      url=row.url,
      resource_kind=row.resource_kind,
      local_path=row.local_path,
      reason="archived file does not exist",
    )
  if not row.sha256:
    return ExtractionFailure(
      url=row.url,
      resource_kind=row.resource_kind,
      local_path=row.local_path,
      reason="archived row has no sha256",
    )
  sha = hashlib.sha256()
  try:
    with local_path.open("rb") as f:
      while chunk := f.read(8192):
        sha.update(chunk)
    actual_sha256 = sha.hexdigest()
  except Exception as exc:
    return ExtractionFailure(
      url=row.url,
      resource_kind=row.resource_kind,
      local_path=row.local_path,
      reason=f"error hashing file: {exc}",
    )
  if actual_sha256 != row.sha256:
    return ExtractionFailure(
      url=row.url,
      resource_kind=row.resource_kind,
      local_path=row.local_path,
      reason="checksum mismatch",
    )
  return None


def _eligible_rows(rows: list[ArchiveManifestRow]) -> list[ArchiveManifestRow]:
  return [
    row
    for row in rows
    if row.archive_state == "archived"
    and row.resource_kind in EXTRACTABLE_RESOURCE_KINDS
  ]


class DatasetPageParser(HTMLParser):
  def __init__(self) -> None:
    super().__init__()
    self.title_parts: list[str] = []
    self.h1_parts: list[str] = []
    self.program = ""
    self.category = ""
    self.availability = ""
    self.links: list[str] = []

    self._in_title = False
    self._in_h1 = False

    self._div_stack: list[str] = []
    self._field_content_div_index: int | None = None
    self._current_field: str | None = None
    self._field_content_parts: list[str] = []

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    attributes = dict(attrs)
    class_attr = attributes.get("class") or ""
    classes = class_attr.split()

    if tag == "title":
      self._in_title = True
    elif tag == "h1" and not self.h1_parts:
      self._in_h1 = True
    elif tag == "a":
      href = attributes.get("href")
      if href:
        self.links.append(href)

    if tag == "div":
      self._div_stack.append(class_attr)

      if "views-field-field-program-type" in classes:
        self._current_field = "program"
      elif "views-field-field-data-file-category" in classes:
        self._current_field = "category"
      elif "views-field-field-availability" in classes:
        self._current_field = "availability"

      if self._current_field is not None and "field-content" in classes:
        self._field_content_div_index = len(self._div_stack) - 1
        self._field_content_parts = []

  def handle_data(self, data: str) -> None:
    if self._in_title:
      self.title_parts.append(data)
    if self._in_h1:
      self.h1_parts.append(data)
    if self._field_content_div_index is not None:
      self._field_content_parts.append(data)

  def handle_endtag(self, tag: str) -> None:
    if tag == "title":
      self._in_title = False
    elif tag == "h1":
      self._in_h1 = False
    elif tag == "div":
      if self._div_stack:
        self._div_stack.pop()
      if self._field_content_div_index is not None:
        if len(self._div_stack) <= self._field_content_div_index:
          val = re.sub(r"\s+", " ", "".join(self._field_content_parts)).strip()
          if self._current_field == "program":
            self.program = val
          elif self._current_field == "category":
            self.category = val
          elif self._current_field == "availability":
            self.availability = val

          self._field_content_div_index = None
          self._current_field = None


def _extract_dataset(
  row: ArchiveManifestRow,
) -> tuple[DatasetMetadataRow, list[OntologyNodeRow], list[OntologyEdgeRow]]:
  dataset_id = _dataset_id_from_url(row.url)
  local_path = Path(row.local_path)

  if row.content_type == "text/html":
    html = local_path.read_text(encoding="utf-8", errors="replace")
    parser = DatasetPageParser()
    parser.feed(html)

    title = "".join(parser.title_parts).strip()
    if not title:
      title = "".join(parser.h1_parts).strip()
    title = re.sub(r"\s+", " ", title)
    if title.endswith(" | ResDAC"):
      title = title[:-9]

    name = title or row.source_title
    program = parser.program
    category = parser.category
    availability = parser.availability
    links = parser.links
  else:
    name = row.source_title
    program = ""
    category = ""
    availability = ""
    links = []

  dataset = DatasetMetadataRow(
    dataset_id=dataset_id,
    name=name,
    program=program,
    category=category,
    availability=availability,
    source_url=row.url,
    local_path=row.local_path,
    sha256=row.sha256,
    extraction_notes="",
  )

  nodes = [
    OntologyNodeRow(
      node_id=dataset_id,
      node_class="Dataset",
      name=name,
      source_url=row.url,
      local_path=row.local_path,
      sha256=row.sha256,
    )
  ]
  edges = []

  if program:
    program_id = f"program_{_slugify(program)}"
    nodes.append(
      OntologyNodeRow(
        node_id=program_id,
        node_class="Program",
        name=program,
        source_url=row.url,
        local_path=row.local_path,
        sha256=row.sha256,
      )
    )
    edges.append(
      OntologyEdgeRow(
        source_id=dataset_id,
        target_id=program_id,
        relationship="belongs_to",
        source_url=row.url,
        local_path=row.local_path,
        sha256=row.sha256,
      )
    )

  seen_related: set[str] = set()
  for href in links:
    try:
      target_url = normalize_url(row.url, href)
      parts = urlparse(target_url)
      path_parts = [p for p in parts.path.split("/") if p]
      if "files" in path_parts:
        files_idx = path_parts.index("files")
        if files_idx + 1 < len(path_parts):
          target_id = _slugify(path_parts[files_idx + 1])
          if target_id != dataset_id and target_id not in seen_related:
            seen_related.add(target_id)
            edges.append(
              OntologyEdgeRow(
                source_id=dataset_id,
                target_id=target_id,
                relationship="related_to",
                source_url=row.url,
                local_path=row.local_path,
                sha256=row.sha256,
              )
            )
    except Exception:
      pass

  return dataset, nodes, edges


def _stable_url_hash(url: str) -> str:
  return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _dataset_id_for_document(row: ArchiveManifestRow) -> str | None:
  if row.resource_kind == "documentation_page":
    return _dataset_id_from_resdac_file_url(row.url)
  if row.source_url:
    return _dataset_id_from_resdac_file_url(row.source_url)
  return _dataset_id_from_resdac_file_url(row.url)


def _document_kind(row: ArchiveManifestRow) -> str:
  if row.resource_kind == "documentation_page":
    return "html"
  return row.asset_kind or "other"


def _extract_document(row: ArchiveManifestRow, dataset_id: str) -> DocumentMetadataRow:
  local_path = Path(row.local_path)
  if row.resource_kind == "documentation_page" and row.content_type == "text/html":
    title = _read_html_title(local_path)
  else:
    title = row.source_title
  document_id = (
    f"{dataset_id}__{_document_suffix_from_url(row.url)}__{_stable_url_hash(row.url)}"
  )
  return DocumentMetadataRow(
    document_id=document_id,
    dataset_id=dataset_id,
    title=title,
    document_kind=_document_kind(row),
    source_url=row.url,
    local_path=row.local_path,
    sha256=row.sha256,
    content_type=row.content_type,
  )


def _edge_for_document(row: DocumentMetadataRow) -> DocumentEdgeRow:
  return DocumentEdgeRow(
    source_id=row.dataset_id,
    target_id=row.document_id,
    source_url=row.source_url,
    local_path=row.local_path,
    sha256=row.sha256,
  )


def _write_model_csv[T: BaseModel](
  rows: list[T], output_path: Path, fieldnames: Sequence[str]
) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      writer.writerow(row.model_dump())


def write_metadata_outputs(result: ExtractionResult) -> None:
  _write_model_csv(
    result.datasets,
    result.config.metadata_dir / "datasets.csv",
    DATASET_FIELDNAMES,
  )
  _write_model_csv(
    result.documents,
    result.config.metadata_dir / "documents.csv",
    DOCUMENT_FIELDNAMES,
  )
  _write_model_csv(
    result.document_edges,
    result.config.graph_dir / "document_edges.csv",
    DOCUMENT_EDGE_FIELDNAMES,
  )
  _write_model_csv(
    result.ontology_nodes,
    result.config.graph_dir / "ontology_nodes.csv",
    ONTOLOGY_NODE_FIELDNAMES,
  )
  _write_model_csv(
    result.ontology_edges,
    result.config.graph_dir / "ontology_edges.csv",
    ONTOLOGY_EDGE_FIELDNAMES,
  )


def write_extraction_workspace_summary(result: ExtractionResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "04_extraction_pack.md"
  lines = [
    "# Extraction Pack",
    "",
    f"- Archive manifest input: {result.config.archive_manifest_path}",
    f"- Manifest rows: {result.manifest_rows}",
    f"- Datasets: {result.dataset_count}",
    f"- Documents: {result.document_count}",
    f"- Document edges: {result.edge_count}",
    f"- Ontology nodes: {result.ontology_node_count}",
    f"- Ontology edges: {result.ontology_edge_count}",
    f"- Failures: {result.failure_count}",
    "",
    "## Outputs",
    "",
    f"- Dataset metadata: {result.config.metadata_dir / 'datasets.csv'}",
    f"- Document metadata: {result.config.metadata_dir / 'documents.csv'}",
    f"- Document graph edges: {result.config.graph_dir / 'document_edges.csv'}",
    f"- Ontology graph nodes: {result.config.graph_dir / 'ontology_nodes.csv'}",
    f"- Ontology graph edges: {result.config.graph_dir / 'ontology_edges.csv'}",
    "",
    "## Unresolved Normalization",
    "",
  ]
  if result.datasets:
    lines.extend(
      sorted(
        {
          f"- {row.dataset_id}: {row.extraction_notes}"
          for row in result.datasets
          if row.extraction_notes
        }
      )
    )
  else:
    lines.append("- None")
  lines.extend(["", "## Failures", ""])
  if result.failures:
    lines.extend(["| url | kind | local_path | reason |", "| --- | --- | --- | --- |"])
    for failure in result.failures[:25]:
      lines.append(
        f"| {failure.url} | {failure.resource_kind} | {failure.local_path} | {failure.reason} |"
      )
    if len(result.failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(result.failures) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_extraction(config: ExtractionConfig) -> tuple[ExtractionResult, Path]:
  manifest_rows = read_archive_manifest_csv(config.archive_manifest_path)
  datasets_by_id: dict[str, DatasetMetadataRow] = {}
  documents_by_id: dict[str, DocumentMetadataRow] = {}
  ontology_nodes: list[OntologyNodeRow] = []
  ontology_edges: list[OntologyEdgeRow] = []
  failures: list[ExtractionFailure] = []

  eligible_rows = _eligible_rows(manifest_rows)

  for row in eligible_rows:
    if row.resource_kind != "dataset_page":
      continue
    failure = _verify_archived_row(row)
    if failure is not None:
      failures.append(failure)
      continue
    dataset, nodes, edges = _extract_dataset(row)
    datasets_by_id[dataset.dataset_id] = dataset
    ontology_nodes.extend(nodes)
    ontology_edges.extend(edges)

  for row in eligible_rows:
    if row.resource_kind not in {"documentation_page", "asset"}:
      continue
    failure = _verify_archived_row(row)
    if failure is not None:
      failures.append(failure)
      continue
    dataset_id = _dataset_id_for_document(row)
    if dataset_id is None:
      failures.append(
        ExtractionFailure(
          url=row.url,
          resource_kind=row.resource_kind,
          local_path=row.local_path,
          reason="document source is not linked to a dataset page",
        )
      )
      continue
    if dataset_id not in datasets_by_id:
      failures.append(
        ExtractionFailure(
          url=row.url,
          resource_kind=row.resource_kind,
          local_path=row.local_path,
          reason="document references missing dataset",
        )
      )
      continue
    document = _extract_document(row, dataset_id)
    documents_by_id[document.document_id] = document

  # Deduplicate ontology nodes by node_id
  unique_nodes: dict[str, OntologyNodeRow] = {}
  for node in ontology_nodes:
    unique_nodes[node.node_id] = node

  documents = list(documents_by_id.values())
  result = ExtractionResult(
    config=config,
    manifest_rows=len(manifest_rows),
    datasets=sorted(datasets_by_id.values(), key=lambda row: row.dataset_id),
    documents=documents,
    document_edges=[_edge_for_document(row) for row in documents],
    ontology_nodes=sorted(unique_nodes.values(), key=lambda node: node.node_id),
    ontology_edges=ontology_edges,
    failures=failures,
  )
  write_metadata_outputs(result)
  summary_path = write_extraction_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Extract provenance-bearing metadata from archived CMS KB files."
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
  config = ExtractionConfig(
    archive_manifest_path=args.archive_manifest,
    metadata_dir=args.metadata_dir,
    graph_dir=args.graph_dir,
    workspace_dir=args.workspace_dir,
  )
  result, summary_path = run_extraction(config)
  print(
    f"wrote {result.dataset_count} datasets, {result.document_count} documents, "
    f"and {result.edge_count} edges to {config.metadata_dir} / "
    f"{config.graph_dir}; summary: {summary_path}"
  )
  return 1 if result.failure_count else 0


__all__ = [
  "DATASET_FIELDNAMES",
  "DOCUMENT_EDGE_FIELDNAMES",
  "DOCUMENT_FIELDNAMES",
  "ONTOLOGY_NODE_FIELDNAMES",
  "ONTOLOGY_EDGE_FIELDNAMES",
  "DatasetMetadataRow",
  "DocumentEdgeRow",
  "DocumentMetadataRow",
  "OntologyNodeRow",
  "OntologyEdgeRow",
  "ExtractionConfig",
  "ExtractionFailure",
  "ExtractionResult",
  "build_arg_parser",
  "main",
  "read_archive_manifest_csv",
  "run_extraction",
  "write_extraction_workspace_summary",
  "write_metadata_outputs",
]
