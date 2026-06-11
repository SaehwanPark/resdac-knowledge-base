"""Phase 2 metadata extraction from archived CMS KB materials."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .archive import ARCHIVE_MANIFEST_FIELDNAMES, ArchiveManifestRow
from .inventory import ResourceKind, parse_page

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
  actual_sha256 = hashlib.sha256(local_path.read_bytes()).hexdigest()
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


def _extract_dataset(row: ArchiveManifestRow) -> DatasetMetadataRow:
  local_path = Path(row.local_path)
  title = _read_html_title(local_path) if row.content_type == "text/html" else ""
  return DatasetMetadataRow(
    dataset_id=_dataset_id_from_url(row.url),
    name=title or row.source_title,
    source_url=row.url,
    local_path=row.local_path,
    sha256=row.sha256,
    extraction_notes="program, category, and availability not normalized",
  )


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
    f"- Failures: {result.failure_count}",
    "",
    "## Outputs",
    "",
    f"- Dataset metadata: {result.config.metadata_dir / 'datasets.csv'}",
    f"- Document metadata: {result.config.metadata_dir / 'documents.csv'}",
    f"- Document graph edges: {result.config.graph_dir / 'document_edges.csv'}",
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
  failures: list[ExtractionFailure] = []

  for row in _eligible_rows(manifest_rows):
    failure = _verify_archived_row(row)
    if failure is not None:
      failures.append(failure)
      continue

    if row.resource_kind == "dataset_page":
      dataset = _extract_dataset(row)
      datasets_by_id[dataset.dataset_id] = dataset

  for row in _eligible_rows(manifest_rows):
    if row.resource_kind not in {"documentation_page", "asset"}:
      continue
    failure = _verify_archived_row(row)
    if failure is not None:
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

  documents = list(documents_by_id.values())
  result = ExtractionResult(
    config=config,
    manifest_rows=len(manifest_rows),
    datasets=sorted(datasets_by_id.values(), key=lambda row: row.dataset_id),
    documents=documents,
    document_edges=[_edge_for_document(row) for row in documents],
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
  "DatasetMetadataRow",
  "DocumentEdgeRow",
  "DocumentMetadataRow",
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
