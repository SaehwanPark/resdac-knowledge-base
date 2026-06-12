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
  OntologyNodeRow,
  OntologyEdgeRow,
  read_archive_manifest_csv,
)
from .variables import VariableEdgeRow, VariableMetadataRow


class QAConfig(BaseModel):
  datasets_metadata_path: Path = Path("data/metadata/datasets.csv")
  documents_metadata_path: Path = Path("data/metadata/documents.csv")
  variables_metadata_path: Path = Path("data/metadata/variables.csv")
  document_edges_path: Path = Path("data/graph/document_edges.csv")
  variable_edges_path: Path = Path("data/graph/variable_edges.csv")
  ontology_nodes_path: Path = Path("data/graph/ontology_nodes.csv")
  ontology_edges_path: Path = Path("data/graph/ontology_edges.csv")
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
  variables_checked: int = 0
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


def read_variables_csv(input_path: Path) -> list[VariableMetadataRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"variables CSV has no header: {input_path}")

    required_headers = [
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
    missing = [h for h in required_headers if h not in reader.fieldnames]
    if missing:
      raise ValueError(f"variables CSV is missing columns: {', '.join(missing)}")

    rows: list[VariableMetadataRow] = []
    for raw_row in reader:
      page_value = raw_row.get("page", "").strip()
      rows.append(
        VariableMetadataRow(
          variable_id=raw_row["variable_id"],
          variable_name=raw_row["variable_name"],
          dataset_id=raw_row["dataset_id"],
          definition=raw_row["definition"],
          aliases=raw_row.get("aliases", ""),
          years=raw_row.get("years", ""),
          source_document=raw_row["source_document"],
          source_url=raw_row["source_url"],
          page=int(page_value) if page_value else None,
          chunk_id=raw_row["chunk_id"],
          extraction_notes=raw_row.get("extraction_notes", ""),
        )
      )
  return rows


def read_variable_edges_csv(input_path: Path) -> list[VariableEdgeRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"variable edges CSV has no header: {input_path}")

    required_headers = [
      "source_id",
      "target_id",
      "relationship",
      "source_url",
      "source_document",
      "page",
      "chunk_id",
    ]
    missing = [h for h in required_headers if h not in reader.fieldnames]
    if missing:
      raise ValueError(f"variable edges CSV is missing columns: {', '.join(missing)}")

    rows: list[VariableEdgeRow] = []
    for raw_row in reader:
      page_value = raw_row.get("page", "").strip()
      rows.append(
        VariableEdgeRow(
          source_id=raw_row["source_id"],
          target_id=raw_row["target_id"],
          relationship=raw_row.get("relationship", "contains"),
          source_url=raw_row["source_url"],
          source_document=raw_row["source_document"],
          page=int(page_value) if page_value else None,
          chunk_id=raw_row["chunk_id"],
        )
      )
  return rows


def read_ontology_nodes_csv(input_path: Path) -> list[OntologyNodeRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"ontology nodes CSV has no header: {input_path}")

    required_headers = ["node_id", "node_class", "name", "source_url", "local_path", "sha256"]
    missing = [h for h in required_headers if h not in reader.fieldnames]
    if missing:
      raise ValueError(f"ontology nodes CSV is missing columns: {', '.join(missing)}")

    rows: list[OntologyNodeRow] = []
    for raw_row in reader:
      rows.append(
        OntologyNodeRow(
          node_id=raw_row["node_id"],
          node_class=raw_row["node_class"],
          name=raw_row.get("name", ""),
          source_url=raw_row["source_url"],
          local_path=raw_row["local_path"],
          sha256=raw_row["sha256"],
        )
      )
  return rows


def read_ontology_edges_csv(input_path: Path) -> list[OntologyEdgeRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"ontology edges CSV has no header: {input_path}")

    required_headers = ["source_id", "target_id", "relationship", "source_url", "local_path", "sha256"]
    missing = [h for h in required_headers if h not in reader.fieldnames]
    if missing:
      raise ValueError(f"ontology edges CSV is missing columns: {', '.join(missing)}")

    rows: list[OntologyEdgeRow] = []
    for raw_row in reader:
      rows.append(
        OntologyEdgeRow(
          source_id=raw_row["source_id"],
          target_id=raw_row["target_id"],
          relationship=raw_row["relationship"],
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
  variables_checked = 0
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

  # Load ontology nodes and edges if present
  variables: list[VariableMetadataRow] = []
  variable_edges: list[VariableEdgeRow] = []
  ontology_nodes: list[OntologyNodeRow] = []
  ontology_edges: list[OntologyEdgeRow] = []

  if config.variables_metadata_path.is_file():
    try:
      variables = read_variables_csv(config.variables_metadata_path)
    except Exception as exc:
      findings.append(
        QAFinding(
          file=str(config.variables_metadata_path),
          item_id="header/parse",
          field="csv_parsing",
          severity="error",
          message=f"Failed to read variables metadata: {exc}",
        )
      )

  if config.variable_edges_path.is_file():
    try:
      variable_edges = read_variable_edges_csv(config.variable_edges_path)
    except Exception as exc:
      findings.append(
        QAFinding(
          file=str(config.variable_edges_path),
          item_id="header/parse",
          field="csv_parsing",
          severity="error",
          message=f"Failed to read variable edges: {exc}",
        )
      )

  if config.ontology_nodes_path.is_file():
    try:
      ontology_nodes = read_ontology_nodes_csv(config.ontology_nodes_path)
    except Exception as exc:
      findings.append(
        QAFinding(
          file=str(config.ontology_nodes_path),
          item_id="header/parse",
          field="csv_parsing",
          severity="error",
          message=f"Failed to read ontology nodes: {exc}",
        )
      )

  if config.ontology_edges_path.is_file():
    try:
      ontology_edges = read_ontology_edges_csv(config.ontology_edges_path)
    except Exception as exc:
      findings.append(
        QAFinding(
          file=str(config.ontology_edges_path),
          item_id="header/parse",
          field="csv_parsing",
          severity="error",
          message=f"Failed to read ontology edges: {exc}",
        )
      )

  if not datasets:
    findings.append(
      QAFinding(
        file="datasets.csv",
        item_id="N/A",
        field="dataset_count",
        severity="error",
        message="Datasets metadata file has zero rows of data",
      )
    )
  if not documents:
    findings.append(
      QAFinding(
        file="documents.csv",
        item_id="N/A",
        field="document_count",
        severity="error",
        message="Documents metadata file has zero rows of data",
      )
    )

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
          severity="error",
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
  variable_ids = {variable.variable_id for variable in variables}
  ontology_node_ids = {node.node_id for node in ontology_nodes}

  seen_dataset_ids: set[str] = set()
  seen_document_ids: set[str] = set()
  seen_variable_ids: set[str] = set()
  seen_ontology_node_ids: set[str] = set()

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

    # Check duplicate dataset_id
    if d_id in seen_dataset_ids:
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id=d_id,
          field="dataset_id",
          severity="error",
          message=f"Duplicate dataset_id encountered: {d_id}",
        )
      )
    seen_dataset_ids.add(d_id)

    # Check leading/trailing whitespace
    if d_id != d_id.strip():
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id=d_id,
          field="dataset_id",
          severity="warning",
          message=f"dataset_id has leading/trailing whitespace: '{d_id}'",
        )
      )
    if d.source_url != d.source_url.strip():
      findings.append(
        QAFinding(
          file="datasets.csv",
          item_id=d_id,
          field="source_url",
          severity="warning",
          message=f"source_url has leading/trailing whitespace: '{d.source_url}'",
        )
      )

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
      else:
        # Verify archive state is 'archived'
        manifest_row = manifest_lookup[d.source_url]
        if manifest_row.archive_state != "archived":
          findings.append(
            QAFinding(
              file="datasets.csv",
              item_id=d_id,
              field="source_url",
              severity="error",
              message=(
                f"source_url archive state is '{manifest_row.archive_state}' "
                f"(expected 'archived') for dataset: {d_id}"
              ),
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

    # Check duplicate document_id
    if doc_id in seen_document_ids:
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="document_id",
          severity="error",
          message=f"Duplicate document_id encountered: {doc_id}",
        )
      )
    seen_document_ids.add(doc_id)

    # Check leading/trailing whitespace
    if doc_id != doc_id.strip():
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="document_id",
          severity="warning",
          message=f"document_id has leading/trailing whitespace: '{doc_id}'",
        )
      )
    if doc.dataset_id != doc.dataset_id.strip():
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="dataset_id",
          severity="warning",
          message=f"dataset_id has leading/trailing whitespace: '{doc.dataset_id}'",
        )
      )
    if doc.source_url != doc.source_url.strip():
      findings.append(
        QAFinding(
          file="documents.csv",
          item_id=doc_id,
          field="source_url",
          severity="warning",
          message=f"source_url has leading/trailing whitespace: '{doc.source_url}'",
        )
      )

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
      else:
        # Verify archive state is 'archived'
        manifest_row = manifest_lookup[doc.source_url]
        if manifest_row.archive_state != "archived":
          findings.append(
            QAFinding(
              file="documents.csv",
              item_id=doc_id,
              field="source_url",
              severity="error",
              message=(
                f"source_url archive state is '{manifest_row.archive_state}' "
                f"(expected 'archived') for document: {doc_id}"
              ),
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

  # 4b. Perform detailed checks on Variables
  for variable in variables:
    variables_checked += 1
    variable_id = variable.variable_id

    if not variable_id or not variable_id.strip():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id="N/A",
          field="variable_id",
          severity="error",
          message="Variable row has empty variable_id",
        )
      )
      continue

    if variable_id in seen_variable_ids:
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="variable_id",
          severity="error",
          message=f"Duplicate variable_id encountered: {variable_id}",
        )
      )
    seen_variable_ids.add(variable_id)

    if variable.variable_id != variable.variable_id.strip():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="variable_id",
          severity="warning",
          message=f"variable_id has leading/trailing whitespace: '{variable.variable_id}'",
        )
      )
    if variable.dataset_id not in dataset_ids:
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="dataset_id",
          severity="error",
          message=f"dataset_id '{variable.dataset_id}' does not exist in datasets metadata",
        )
      )
    if not variable.variable_name.strip():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="variable_name",
          severity="error",
          message="Variable row has empty variable_name",
        )
      )
    if not variable.definition.strip():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="definition",
          severity="warning",
          message="Variable row has empty definition",
        )
      )
    if not variable.chunk_id.strip():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="chunk_id",
          severity="error",
          message="Variable row has empty chunk_id",
        )
      )

    if not is_valid_url(variable.source_url):
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {variable.source_url}",
        )
      )
    elif variable.source_url not in manifest_lookup:
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="source_url",
          severity="error",
          message=f"source_url not found in archive manifest: {variable.source_url}",
        )
      )

    source_document = variable.source_document.strip()
    if not source_document:
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="source_document",
          severity="error",
          message="Empty source_document for variable",
        )
      )
    elif not Path(source_document).is_file():
      findings.append(
        QAFinding(
          file="variables.csv",
          item_id=variable_id,
          field="source_document",
          severity="error",
          message=f"Source document does not exist: {source_document}",
        )
      )

  # 5. Perform detailed checks on Edges
  for edge_idx, edge in enumerate(edges):
    edges_checked += 1
    edge_label = f"Line {edge_idx + 2}"

    # Verify ID references
    if edge.source_id not in dataset_ids and edge.source_id not in document_ids:
      findings.append(
        QAFinding(
          file="document_edges.csv",
          item_id=edge_label,
          field="source_id",
          severity="error",
          message=f"source_id '{edge.source_id}' does not map to any dataset or document",
        )
      )

    if edge.target_id not in dataset_ids and edge.target_id not in document_ids:
      findings.append(
        QAFinding(
          file="document_edges.csv",
          item_id=edge_label,
          field="target_id",
          severity="error",
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

  # 5a. Perform detailed checks on Variable Edges
  for edge_idx, edge in enumerate(variable_edges):
    edges_checked += 1
    edge_label = f"Line {edge_idx + 2}"

    if edge.source_id not in dataset_ids:
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="source_id",
          severity="error",
          message=f"source_id '{edge.source_id}' does not map to any dataset",
        )
      )

    if edge.target_id not in variable_ids:
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="target_id",
          severity="error",
          message=f"target_id '{edge.target_id}' does not map to any variable",
        )
      )

    if edge.relationship != "contains":
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="relationship",
          severity="warning",
          message=f"Unexpected variable relationship: {edge.relationship}",
        )
      )

    if not is_valid_url(edge.source_url):
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {edge.source_url}",
        )
      )
    elif edge.source_url not in manifest_lookup:
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="source_url",
          severity="error",
          message=f"source_url not found in archive manifest: {edge.source_url}",
        )
      )

    source_document = edge.source_document.strip()
    if not source_document:
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="source_document",
          severity="error",
          message="Empty source_document for variable edge",
        )
      )
    elif not Path(source_document).is_file():
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="source_document",
          severity="error",
          message=f"Source document does not exist: {source_document}",
        )
      )

    if not edge.chunk_id.strip():
      findings.append(
        QAFinding(
          file="variable_edges.csv",
          item_id=edge_label,
          field="chunk_id",
          severity="error",
          message="Variable edge has empty chunk_id",
        )
      )

  # 5b. Perform detailed checks on Ontology Nodes and Edges
  for node in ontology_nodes:
    node_id = node.node_id
    if not node_id or not node_id.strip():
      findings.append(
        QAFinding(
          file="ontology_nodes.csv",
          item_id="N/A",
          field="node_id",
          severity="error",
          message="Ontology node row has empty node_id",
        )
      )
      continue

    if node_id in seen_ontology_node_ids:
      findings.append(
        QAFinding(
          file="ontology_nodes.csv",
          item_id=node_id,
          field="node_id",
          severity="error",
          message=f"Duplicate ontology node_id encountered: {node_id}",
        )
      )
    seen_ontology_node_ids.add(node_id)

    if node.node_class not in {"Dataset", "Table", "Variable", "Program"}:
      findings.append(
        QAFinding(
          file="ontology_nodes.csv",
          item_id=node_id,
          field="node_class",
          severity="error",
          message=f"Invalid node_class '{node.node_class}' for node {node_id}",
        )
      )

    # Check URL
    if not is_valid_url(node.source_url):
      findings.append(
        QAFinding(
          file="ontology_nodes.csv",
          item_id=node_id,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {node.source_url}",
        )
      )
    else:
      if node.source_url not in manifest_lookup:
        findings.append(
          QAFinding(
            file="ontology_nodes.csv",
            item_id=node_id,
            field="source_url",
            severity="error",
            message=f"source_url not found in archive manifest: {node.source_url}",
          )
        )

    # Check local path existence and checksum
    local_path_str = node.local_path.strip()
    if not local_path_str:
      findings.append(
        QAFinding(
          file="ontology_nodes.csv",
          item_id=node_id,
          field="local_path",
          severity="error",
          message="Empty local_path for ontology node",
        )
      )
    else:
      local_path = Path(local_path_str)
      if not local_path.is_file():
        findings.append(
          QAFinding(
            file="ontology_nodes.csv",
            item_id=node_id,
            field="local_path",
            severity="error",
            message=f"Local file does not exist: {local_path_str}",
          )
        )
      else:
        try:
          actual_sha = compute_sha256(local_path)
          if actual_sha != node.sha256:
            findings.append(
              QAFinding(
                file="ontology_nodes.csv",
                item_id=node_id,
                field="sha256",
                severity="error",
                message=f"Checksum mismatch. Metadata: {node.sha256}, Actual: {actual_sha}",
              )
            )
        except Exception as exc:
          findings.append(
            QAFinding(
              file="ontology_nodes.csv",
              item_id=node_id,
              field="sha256",
              severity="error",
              message=f"Error computing checksum: {exc}",
            )
          )

  valid_target_ids = dataset_ids | document_ids | variable_ids | ontology_node_ids
  for edge_idx, edge in enumerate(ontology_edges):
    edge_label = f"Line {edge_idx + 2}"

    if edge.source_id not in valid_target_ids:
      findings.append(
        QAFinding(
          file="ontology_edges.csv",
          item_id=edge_label,
          field="source_id",
          severity="error",
          message=f"source_id '{edge.source_id}' does not map to any dataset, document, or ontology node",
        )
      )

    if edge.target_id not in valid_target_ids:
      findings.append(
        QAFinding(
          file="ontology_edges.csv",
          item_id=edge_label,
          field="target_id",
          severity="warning",
          message=f"target_id '{edge.target_id}' does not map to any dataset, document, or ontology node",
        )
      )

    if edge.source_url and not is_valid_url(edge.source_url):
      findings.append(
        QAFinding(
          file="ontology_edges.csv",
          item_id=edge_label,
          field="source_url",
          severity="error",
          message=f"Invalid source_url: {edge.source_url}",
        )
      )
    elif edge.source_url:
      if edge.source_url not in manifest_lookup:
        findings.append(
          QAFinding(
            file="ontology_edges.csv",
            item_id=edge_label,
            field="source_url",
            severity="error",
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
            file="ontology_edges.csv",
            item_id=edge_label,
            field="local_path",
            severity="error",
            message=f"Local file does not exist: {local_path_str}",
          )
        )
      elif edge.sha256.strip():
        try:
          actual_sha = compute_sha256(local_path)
          if actual_sha != edge.sha256:
            findings.append(
              QAFinding(
                file="ontology_edges.csv",
                item_id=edge_label,
                field="sha256",
                severity="error",
                message=f"Checksum mismatch. Edge: {edge.sha256}, Actual: {actual_sha}",
              )
            )
        except Exception as exc:
          findings.append(
            QAFinding(
              file="ontology_edges.csv",
              item_id=edge_label,
              field="sha256",
              severity="error",
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
    major_error_types = {
      "csv_parsing",
      "file_existence",
      "dataset_id",
      "document_id",
      "dataset_count",
      "document_count",
      "node_class",
      "node_id",
      "variable_id",
      "variable_name",
      "source_id",
      "target_id",
      "source_document",
      "chunk_id",
    }
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
    variables_checked=variables_checked,
    edges_checked=edges_checked + len(ontology_edges),
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
    f"- Variables Checked: {result.variables_checked}",
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
    "--variables-metadata",
    type=Path,
    default=Path("data/metadata/variables.csv"),
  )
  parser.add_argument(
    "--document-edges",
    type=Path,
    default=Path("data/graph/document_edges.csv"),
  )
  parser.add_argument(
    "--variable-edges",
    type=Path,
    default=Path("data/graph/variable_edges.csv"),
  )
  parser.add_argument(
    "--ontology-nodes",
    type=Path,
    default=Path("data/graph/ontology_nodes.csv"),
  )
  parser.add_argument(
    "--ontology-edges",
    type=Path,
    default=Path("data/graph/ontology_edges.csv"),
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
    variables_metadata_path=args.variables_metadata,
    document_edges_path=args.document_edges,
    variable_edges_path=args.variable_edges,
    ontology_nodes_path=args.ontology_nodes,
    ontology_edges_path=args.ontology_edges,
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
