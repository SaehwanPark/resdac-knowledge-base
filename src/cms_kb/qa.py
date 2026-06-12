"""Phase 4 QA Specialist and provenance validation for CMS KB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .extraction import (
  DatasetMetadataRow,
  DocumentEdgeRow,
  DocumentMetadataRow,
  read_archive_manifest_csv,
)


class QAConfig(BaseModel):
  datasets_metadata_path: Path = Path("data/metadata/datasets.csv")
  documents_metadata_path: Path = Path("data/metadata/documents.csv")
  document_edges_path: Path = Path("data/graph/document_edges.csv")
  archive_manifest_path: Path = Path("manifests/archive_manifest.csv")
  workspace_dir: Path = Path("_workspace")


class QAFinding(BaseModel):
  file: str
  item_id: str
  field: str
  severity: Literal["warning", "error"]
  message: str


class QAResult(BaseModel):
  config: QAConfig
  verdict: Literal["pass", "fix", "redo"]
  findings: list[QAFinding] = Field(default_factory=list)
  datasets_checked: int = 0
  documents_checked: int = 0
  edges_checked: int = 0

  @property
  def error_count(self) -> int:
    return sum(1 for f in self.findings if f.severity == "error")

  @property
  def warning_count(self) -> int:
    return sum(1 for f in self.findings if f.severity == "warning")


def read_datasets_csv(input_path: Path) -> list[DatasetMetadataRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"datasets CSV has no header: {input_path}")

    rows: list[DatasetMetadataRow] = []
    for raw_row in reader:
      rows.append(
        DatasetMetadataRow(
          dataset_id=raw_row["dataset_id"],
          name=raw_row.get("name", ""),
          program=raw_row.get("program", ""),
          category=raw_row.get("category", ""),
          availability=raw_row.get("availability", ""),
          source_url=raw_row["source_url"],
          local_path=raw_row["local_path"],
          sha256=raw_row["sha256"],
          extraction_notes=raw_row.get("extraction_notes", ""),
        )
      )
  return rows


def read_documents_csv(input_path: Path) -> list[DocumentMetadataRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"documents CSV has no header: {input_path}")

    rows: list[DocumentMetadataRow] = []
    for raw_row in reader:
      rows.append(
        DocumentMetadataRow(
          document_id=raw_row["document_id"],
          dataset_id=raw_row["dataset_id"],
          title=raw_row.get("title", ""),
          document_kind=raw_row["document_kind"],
          source_url=raw_row["source_url"],
          local_path=raw_row["local_path"],
          sha256=raw_row["sha256"],
          content_type=raw_row.get("content_type", ""),
          extraction_notes=raw_row.get("extraction_notes", ""),
        )
      )
  return rows


def read_document_edges_csv(input_path: Path) -> list[DocumentEdgeRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"document edges CSV has no header: {input_path}")

    rows: list[DocumentEdgeRow] = []
    for raw_row in reader:
      rows.append(
        DocumentEdgeRow(
          source_id=raw_row["source_id"],
          target_id=raw_row["target_id"],
          relationship=raw_row.get("relationship", "has_document"),
          source_url=raw_row["source_url"],
          local_path=raw_row["local_path"],
          sha256=raw_row["sha256"],
        )
      )
  return rows


def compute_sha256(path: Path) -> str:
  sha256 = hashlib.sha256()
  with path.open("rb") as f:
    while chunk := f.read(8192):
      sha256.update(chunk)
  return sha256.hexdigest()


def is_valid_url(url: str) -> bool:
  try:
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)
  except Exception:
    return False


def run_qa(config: QAConfig) -> tuple[QAResult, Path]:
  findings: list[QAFinding] = []
  datasets_checked = 0
  documents_checked = 0
  edges_checked = 0

  # 1. Basic File Existence Checks (Fatal if missing datasets/documents/manifest)
  fatal_missing = False
  for name, path in [
    ("datasets metadata", config.datasets_metadata_path),
    ("documents metadata", config.documents_metadata_path),
    ("archive manifest", config.archive_manifest_path),
  ]:
    if not path.is_file():
      findings.append(
        QAFinding(
          file=str(path),
          item_id="N/A",
          field="file_existence",
          severity="error",
          message=f"Required {name} file is missing",
        )
      )
      fatal_missing = True

  if fatal_missing:
    result = QAResult(
      config=config,
      verdict="redo",
      findings=findings,
    )
    summary_path = write_qa_workspace_summary(result)
    return result, summary_path

  # 2. Load manifest and CSVs (Fatal if schema/parsing errors)
  try:
    manifest_rows = read_archive_manifest_csv(config.archive_manifest_path)
    manifest_lookup = {r.url: r for r in manifest_rows}
  except Exception as exc:
    findings.append(
      QAFinding(
        file=str(config.archive_manifest_path),
        item_id="header/parse",
        field="csv_parsing",
        severity="error",
        message=f"Failed to read archive manifest: {exc}",
      )
    )
    result = QAResult(
      config=config,
      verdict="redo",
      findings=findings,
    )
    summary_path = write_qa_workspace_summary(result)
    return result, summary_path

  try:
    datasets = read_datasets_csv(config.datasets_metadata_path)
  except Exception as exc:
    findings.append(
      QAFinding(
        file=str(config.datasets_metadata_path),
        item_id="header/parse",
        field="csv_parsing",
        severity="error",
        message=f"Failed to read datasets metadata: {exc}",
      )
    )
    result = QAResult(
      config=config,
      verdict="redo",
      findings=findings,
    )
    summary_path = write_qa_workspace_summary(result)
    return result, summary_path

  try:
    documents = read_documents_csv(config.documents_metadata_path)
  except Exception as exc:
    findings.append(
      QAFinding(
        file=str(config.documents_metadata_path),
        item_id="header/parse",
        field="csv_parsing",
        severity="error",
        message=f"Failed to read documents metadata: {exc}",
      )
    )
    result = QAResult(
      config=config,
      verdict="redo",
      findings=findings,
    )
    summary_path = write_qa_workspace_summary(result)
    return result, summary_path

  edges: list[DocumentEdgeRow] = []
  if config.document_edges_path.is_file():
    try:
      edges = read_document_edges_csv(config.document_edges_path)
    except Exception as exc:
      findings.append(
        QAFinding(
          file=str(config.document_edges_path),
          item_id="header/parse",
          field="csv_parsing",
          severity="warning",
          message=f"Failed to read document edges: {exc}",
        )
      )
  else:
    findings.append(
      QAFinding(
        file=str(config.document_edges_path),
        item_id="N/A",
        field="file_existence",
        severity="warning",
        message="Document edges CSV file is missing",
      )
    )

  # Index datasets by ID for reference integrity checks
  dataset_ids = {d.dataset_id for d in datasets}
  document_ids = {doc.document_id for doc in documents}

  # 3. Perform detailed checks on Datasets
  for d in datasets:
    datasets_checked += 1
    d_id = d.dataset_id

    # Check ID structure
    if not d_id or not d_id.strip():
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id="N/A",
          field="dataset_id",
          severity="error",
          message="Dataset row has empty dataset_id",
        )
      )
      continue

    # Check URL
    if not is_valid_url(d.source_url):
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id=d_id,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {d.source_url}",
        )
      )
    else:
      # Provenance URL lookup check in manifest
      if d.source_url not in manifest_lookup:
        findings.append(
          QAFinding(
            file="datasets.csv",
            item_id=d_id,
            field="source_url",
            severity="error",
            message=f"source_url not found in archive manifest: {d.source_url}",
          )
        )

    # Check local file existence and integrity
    local_path_str = d.local_path.strip()
    if not local_path_str:
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id=d_id,
          field="local_path",
          severity="error",
          message="Empty local_path for dataset",
        )
      )
    else:
      local_path = Path(local_path_str)
      if not local_path.is_file():
        findings.append(
          QAFinding(
            file="datasets.csv",
            item_id=d_id,
            field="local_path",
            severity="error",
            message=f"Local file does not exist: {local_path_str}",
          )
        )
      else:
        # Verify file checksum
        try:
          actual_sha = compute_sha256(local_path)
          if actual_sha != d.sha256:
            findings.append(
              QAFinding(
                file="datasets.csv",
                item_id=d_id,
                field="sha256",
                severity="error",
                message=f"Checksum mismatch. Metadata: {d.sha256}, Actual: {actual_sha}",
              )
            )

          # Manifest cross check
          manifest_row = manifest_lookup.get(d.source_url)
          if manifest_row and manifest_row.sha256 != actual_sha:
            findings.append(
              QAFinding(
                file="datasets.csv",
                item_id=d_id,
                field="sha256",
                severity="error",
                message=(
                  f"Checksum mismatch with manifest. Manifest: {manifest_row.sha256}, "
                  f"Actual: {actual_sha}"
                ),
              )
            )
        except Exception as exc:
          findings.append(
            QAFinding(
              file="datasets.csv",
              item_id=d_id,
              field="sha256",
              severity="error",
              message=f"Error computing checksum: {exc}",
            )
          )

  # 4. Perform detailed checks on Documents
  for doc in documents:
    documents_checked += 1
    doc_id = doc.document_id

    # Check ID structure
    if not doc_id or not doc_id.strip():
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id="N/A",
          field="document_id",
          severity="error",
          message="Document row has empty document_id",
        )
      )
      continue

    # Reference integrity check
    if doc.dataset_id not in dataset_ids:
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="dataset_id",
          severity="error",
          message=f"dataset_id '{doc.dataset_id}' does not exist in datasets metadata",
        )
      )

    # Check URL
    if not is_valid_url(doc.source_url):
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {doc.source_url}",
        )
      )
    else:
      # Provenance URL lookup check in manifest
      if doc.source_url not in manifest_lookup:
        findings.append(
          QAFinding(
            file="documents.csv",
            item_id=doc_id,
            field="source_url",
            severity="error",
            message=f"source_url not found in archive manifest: {doc.source_url}",
          )
        )

    # Check local file existence and integrity
    local_path_str = doc.local_path.strip()
    if not local_path_str:
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="local_path",
          severity="error",
          message="Empty local_path for document",
        )
      )
    else:
      local_path = Path(local_path_str)
      if not local_path.is_file():
        findings.append(
          QAFinding(
            file="documents.csv",
            item_id=doc_id,
            field="local_path",
            severity="error",
            message=f"Local file does not exist: {local_path_str}",
          )
        )
      else:
        # Verify file checksum
        try:
          actual_sha = compute_sha256(local_path)
          if actual_sha != doc.sha256:
            findings.append(
              QAFinding(
                file="documents.csv",
                item_id=doc_id,
                field="sha256",
                severity="error",
                message=f"Checksum mismatch. Metadata: {doc.sha256}, Actual: {actual_sha}",
              )
            )

          # Manifest cross check
          manifest_row = manifest_lookup.get(doc.source_url)
          if manifest_row and manifest_row.sha256 != actual_sha:
            findings.append(
              QAFinding(
                file="documents.csv",
                item_id=doc_id,
                field="sha256",
                severity="error",
                message=(
                  f"Checksum mismatch with manifest. Manifest: {manifest_row.sha256}, "
                  f"Actual: {actual_sha}"
                ),
              )
            )
        except Exception as exc:
          findings.append(
            QAFinding(
              file="documents.csv",
              item_id=doc_id,
              field="sha256",
              severity="error",
              message=f"Error computing checksum: {exc}",
            )
          )

  # 5. Perform detailed checks on Edges
  for edge_idx, edge in enumerate(edges):
    edges_checked += 1
    edge_label = f"edge_{edge_idx}"

    # Verify ID references
    if edge.source_id not in dataset_ids and edge.source_id not in document_ids:
      findings.append(
        QAFinding(
          file="document_edges.csv",
          item_id=edge_label,
          field="source_id",
          severity="warning",
          message=f"source_id '{edge.source_id}' does not map to any dataset or document",
        )
      )

    if edge.target_id not in dataset_ids and edge.target_id not in document_ids:
      findings.append(
        QAFinding(
          file="document_edges.csv",
          item_id=edge_label,
          field="target_id",
          severity="warning",
          message=f"target_id '{edge.target_id}' does not map to any dataset or document",
        )
      )

    # Check URL
    if edge.source_url and not is_valid_url(edge.source_url):
      findings.append(
        QAFinding(
          file="document_edges.csv",
          item_id=edge_label,
          field="source_url",
          severity="warning",
          message=f"Invalid source_url: {edge.source_url}",
        )
      )
    elif edge.source_url:
      if edge.source_url not in manifest_lookup:
        findings.append(
          QAFinding(
            file="document_edges.csv",
            item_id=edge_label,
            field="source_url",
            severity="warning",
            message=f"source_url not found in archive manifest: {edge.source_url}",
          )
        )

    # Check local path existence and checksum if provided
    local_path_str = edge.local_path.strip()
    if local_path_str:
      local_path = Path(local_path_str)
      if not local_path.is_file():
        findings.append(
          QAFinding(
            file="document_edges.csv",
            item_id=edge_label,
            field="local_path",
            severity="warning",
            message=f"Local file does not exist: {local_path_str}",
          )
        )
      elif edge.sha256.strip():
        try:
          actual_sha = compute_sha256(local_path)
          if actual_sha != edge.sha256:
            findings.append(
              QAFinding(
                file="document_edges.csv",
                item_id=edge_label,
                field="sha256",
                severity="warning",
                message=f"Checksum mismatch. Edge: {edge.sha256}, Actual: {actual_sha}",
              )
            )
        except Exception as exc:
          findings.append(
            QAFinding(
              file="document_edges.csv",
              item_id=edge_label,
              field="sha256",
              severity="warning",
              message=f"Error computing checksum: {exc}",
            )
          )

  # 6. Verdict Assignment
  # pass = no errors and no warnings (or only warnings)
  # fix = has errors, but they are bounded/fixable (e.g. checksum mismatches or missing local files)
  # redo = major structural issues or too many errors
  errors = [f for f in findings if f.severity == "error"]

  if not errors:
    verdict = "pass"
  else:
    # If there are major structural errors (e.g., missing CSV files, header parser failures,
    # or reference integrity violations), return redo.
    major_error_types = {"csv_parsing", "file_existence", "dataset_id", "document_id"}
    has_major_error = any(f.field in major_error_types for f in errors)

    # Reference integrity check errors
    has_ref_integrity_error = any(
      "does not exist in datasets metadata" in f.message for f in errors
    )

    # If errors are many (> 5), suggest redoing the crawl/archival
    if has_major_error or has_ref_integrity_error or len(errors) > 5:
      verdict = "redo"
    else:
      verdict = "fix"

  result = QAResult(
    config=config,
    verdict=verdict,
    findings=findings,
    datasets_checked=datasets_checked,
    documents_checked=documents_checked,
    edges_checked=edges_checked,
  )

  summary_path = write_qa_workspace_summary(result)
  return result, summary_path


def write_qa_workspace_summary(result: QAResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  # According to team-spec.md, the file path must be _workspace/06_qa_review.md
  summary_path = result.config.workspace_dir / "06_qa_review.md"

  lines = [
    "# QA Review",
    "",
    f"- Verdict: **{result.verdict.upper()}**",
    "",
    "## Metadata Checked",
    "",
    f"- Datasets Checked: {result.datasets_checked}",
    f"- Documents Checked: {result.documents_checked}",
    f"- Edges Checked: {result.edges_checked}",
    f"- Total Findings: {len(result.findings)}",
    f"  - Errors: {result.error_count}",
    f"  - Warnings: {result.warning_count}",
    "",
    "## Findings",
    "",
  ]

  if result.findings:
    lines.extend(["| File | Item ID | Field | Severity | Message |", "| --- | --- | --- | --- | --- |"])
    for finding in result.findings:
      message_safe = finding.message.replace("|", "\\|").replace("\n", " ")
      lines.append(
        f"| {finding.file} | {finding.item_id} | {finding.field} | {finding.severity} | {message_safe} |"
      )
  else:
    lines.append("- No issues identified.")

  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Validate metadata outputs, checksums, and provenance links."
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
    "--document-edges",
    type=Path,
    default=Path("data/graph/document_edges.csv"),
  )
  parser.add_argument(
    "--archive-manifest",
    type=Path,
    default=Path("manifests/archive_manifest.csv"),
  )
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = QAConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    document_edges_path=args.document_edges,
    archive_manifest_path=args.archive_manifest,
    workspace_dir=args.workspace_dir,
  )
  try:
    result, summary_path = run_qa(config)
    print(
      f"QA review finished with verdict: {result.verdict.upper()}; "
      f"{result.error_count} errors, {result.warning_count} warnings; "
      f"summary written to {summary_path}"
    )
    # exit 0 only if QA passes, 1 if fix/redo or execution failure
    return 0 if result.verdict == "pass" else 1
  except Exception as exc:
    print(f"Error executing QA Specialist: {exc}", file=sys.stderr)
    return 1


__all__ = [
  "QAConfig",
  "QAFinding",
  "QAResult",
  "build_arg_parser",
  "main",
  "run_qa",
]
