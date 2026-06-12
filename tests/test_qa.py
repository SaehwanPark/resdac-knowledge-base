from __future__ import annotations

import csv
import hashlib
from pathlib import Path


from cms_kb.archive import ArchiveManifestRow, write_archive_manifest
from cms_kb.qa import (
  QAConfig,
  QAFinding,
  main,
  run_qa,
)


def _write_file(path: Path, content: bytes) -> str:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(content)
  return hashlib.sha256(content).hexdigest()


def test_qa_finding_model() -> None:
  finding = QAFinding(
    file="datasets.csv",
    item_id="ds-1",
    field="sha256",
    severity="error",
    message="test message",
  )
  assert finding.file == "datasets.csv"
  assert finding.severity == "error"


def test_run_qa_success_flow(tmp_path: Path) -> None:
  # 1. Setup paths
  metadata_dir = tmp_path / "data" / "metadata"
  graph_dir = tmp_path / "data" / "graph"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  workspace_dir = tmp_path / "_workspace"

  for d in [metadata_dir, graph_dir, manifest_dir, raw_dir, workspace_dir]:
    d.mkdir(parents=True, exist_ok=True)

  # 2. Write mock raw files
  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  doc_pdf = raw_dir / "doc-1.pdf"
  doc_sha = _write_file(doc_pdf, b"%PDF fake doc")

  # 3. Write archive manifest
  manifest_path = manifest_dir / "archive_manifest.csv"
  manifest_rows = [
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    ),
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1/doc-1",
      resource_kind="documentation_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=doc_sha,
      local_path=str(doc_pdf),
    ),
  ]
  write_archive_manifest(manifest_rows, manifest_path)

  # 4. Write datasets metadata CSV
  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "dataset_id",
      "name",
      "program",
      "category",
      "availability",
      "source_url",
      "local_path",
      "sha256",
      "extraction_notes",
    ])
    writer.writerow([
      "ds-1",
      "Dataset 1",
      "Medicare",
      "Claims",
      "Available",
      "https://resdac.org/cms-data/files/ds-1",
      str(ds_html),
      ds_sha,
      "",
    ])

  # 5. Write documents metadata CSV
  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "document_id",
      "dataset_id",
      "title",
      "document_kind",
      "source_url",
      "local_path",
      "sha256",
      "content_type",
      "extraction_notes",
    ])
    writer.writerow([
      "doc-1",
      "ds-1",
      "Doc 1 Title",
      "pdf",
      "https://resdac.org/cms-data/files/ds-1/doc-1",
      str(doc_pdf),
      doc_sha,
      "application/pdf",
      "",
    ])

  # 6. Write document edges CSV
  edges_csv = graph_dir / "document_edges.csv"
  with edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "source_id",
      "target_id",
      "relationship",
      "source_url",
      "local_path",
      "sha256",
    ])
    writer.writerow([
      "ds-1",
      "doc-1",
      "has_document",
      "https://resdac.org/cms-data/files/ds-1/doc-1",
      str(doc_pdf),
      doc_sha,
    ])

  # 7. Run QA verification
  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    document_edges_path=edges_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=workspace_dir,
  )

  result, summary_path = run_qa(config)

  # 8. Assertions
  assert result.verdict == "pass"
  assert len(result.findings) == 0
  assert result.datasets_checked == 1
  assert result.documents_checked == 1
  assert result.edges_checked == 1
  assert summary_path.exists()

  # Check CLI command main exit code
  exit_code = main([
    "--datasets-metadata",
    str(datasets_csv),
    "--documents-metadata",
    str(documents_csv),
    "--document-edges",
    str(edges_csv),
    "--archive-manifest",
    str(manifest_path),
    "--workspace-dir",
    str(workspace_dir),
  ])
  assert exit_code == 0


def test_run_qa_validates_variable_metadata_and_edges(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  graph_dir = tmp_path / "data" / "graph"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  workspace_dir = tmp_path / "_workspace"

  for d in [metadata_dir, graph_dir, manifest_dir, raw_dir, workspace_dir]:
    d.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")
  doc_txt = tmp_path / "data" / "parsed" / "html" / "doc-1.txt"
  _write_file(doc_txt, b"BENE_ID: Beneficiary identifier.")

  manifest_path = manifest_dir / "archive_manifest.csv"
  source_url = "https://resdac.org/cms-data/files/ds-1"
  write_archive_manifest(
    [
      ArchiveManifestRow(
        url=source_url,
        resource_kind="dataset_page",
        archive_state="archived",
        downloaded_at_utc="2026-06-11T12:00:00Z",
        sha256=ds_sha,
        local_path=str(ds_html),
      )
    ],
    manifest_path,
  )

  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "dataset_id",
      "name",
      "program",
      "category",
      "availability",
      "source_url",
      "local_path",
      "sha256",
      "extraction_notes",
    ])
    writer.writerow([
      "ds-1",
      "Dataset 1",
      "Medicare",
      "Claims",
      "Available",
      source_url,
      str(ds_html),
      ds_sha,
      "",
    ])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "document_id",
      "dataset_id",
      "title",
      "document_kind",
      "source_url",
      "local_path",
      "sha256",
      "content_type",
      "extraction_notes",
    ])
    writer.writerow([
      "doc-1",
      "ds-1",
      "Doc 1 Title",
      "html",
      source_url,
      str(ds_html),
      ds_sha,
      "text/html",
      "",
    ])

  document_edges_csv = graph_dir / "document_edges.csv"
  with document_edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "source_id",
      "target_id",
      "relationship",
      "source_url",
      "local_path",
      "sha256",
    ])

  variables_csv = metadata_dir / "variables.csv"
  with variables_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
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
    ])
    writer.writerow([
      "ds-1__var__bene-id",
      "BENE_ID",
      "ds-1",
      "Beneficiary identifier",
      "",
      "2020",
      str(doc_txt),
      source_url,
      "",
      "chunk-1",
      "",
    ])

  variable_edges_csv = graph_dir / "variable_edges.csv"
  with variable_edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "source_id",
      "target_id",
      "relationship",
      "source_url",
      "source_document",
      "page",
      "chunk_id",
    ])
    writer.writerow([
      "ds-1",
      "ds-1__var__bene-id",
      "contains",
      source_url,
      str(doc_txt),
      "",
      "chunk-1",
    ])

  result, _ = run_qa(
    QAConfig(
      datasets_metadata_path=datasets_csv,
      documents_metadata_path=documents_csv,
      variables_metadata_path=variables_csv,
      document_edges_path=document_edges_csv,
      variable_edges_path=variable_edges_csv,
      archive_manifest_path=manifest_path,
      workspace_dir=workspace_dir,
    )
  )

  assert result.verdict == "pass"
  assert result.variables_checked == 1
  assert result.edges_checked == 1


def test_run_qa_treats_variable_reference_errors_as_redo(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  graph_dir = tmp_path / "data" / "graph"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  workspace_dir = tmp_path / "_workspace"

  for d in [metadata_dir, graph_dir, manifest_dir, raw_dir, workspace_dir]:
    d.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")
  source_url = "https://resdac.org/cms-data/files/ds-1"
  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest(
    [
      ArchiveManifestRow(
        url=source_url,
        resource_kind="dataset_page",
        archive_state="archived",
        downloaded_at_utc="2026-06-11T12:00:00Z",
        sha256=ds_sha,
        local_path=str(ds_html),
      )
    ],
    manifest_path,
  )

  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "dataset_id",
      "name",
      "program",
      "category",
      "availability",
      "source_url",
      "local_path",
      "sha256",
      "extraction_notes",
    ])
    writer.writerow([
      "ds-1",
      "Dataset 1",
      "Medicare",
      "Claims",
      "Available",
      source_url,
      str(ds_html),
      ds_sha,
      "",
    ])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "document_id",
      "dataset_id",
      "title",
      "document_kind",
      "source_url",
      "local_path",
      "sha256",
      "content_type",
      "extraction_notes",
    ])
    writer.writerow([
      "doc-1",
      "ds-1",
      "Doc 1 Title",
      "html",
      source_url,
      str(ds_html),
      ds_sha,
      "text/html",
      "",
    ])

  document_edges_csv = graph_dir / "document_edges.csv"
  with document_edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "source_id",
      "target_id",
      "relationship",
      "source_url",
      "local_path",
      "sha256",
    ])

  variables_csv = metadata_dir / "variables.csv"
  with variables_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
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
    ])
    writer.writerow([
      "missing-dataset__var__bene-id",
      "BENE_ID",
      "missing-dataset",
      "Beneficiary identifier",
      "",
      "",
      str(ds_html),
      source_url,
      "",
      "chunk-1",
      "",
    ])

  result, _ = run_qa(
    QAConfig(
      datasets_metadata_path=datasets_csv,
      documents_metadata_path=documents_csv,
      variables_metadata_path=variables_csv,
      document_edges_path=document_edges_csv,
      archive_manifest_path=manifest_path,
      workspace_dir=workspace_dir,
    )
  )

  assert result.verdict == "redo"
  assert any(f.file == "variables.csv" and f.field == "dataset_id" for f in result.findings)


def test_run_qa_file_missing(tmp_path: Path) -> None:
  # Check missing files verdict (Fatal REDO)
  config = QAConfig(
    datasets_metadata_path=tmp_path / "non_existent_datasets.csv",
    documents_metadata_path=tmp_path / "non_existent_documents.csv",
    document_edges_path=tmp_path / "non_existent_edges.csv",
    archive_manifest_path=tmp_path / "non_existent_manifest.csv",
    workspace_dir=tmp_path / "_workspace",
  )

  result, summary_path = run_qa(config)
  assert result.verdict == "redo"
  # At least 3 errors for missing datasets, documents, and manifest
  assert len(result.findings) >= 3
  assert any("Required datasets metadata file is missing" in f.message for f in result.findings)
  assert any("Required documents metadata file is missing" in f.message for f in result.findings)
  assert any("Required archive manifest file is missing" in f.message for f in result.findings)


def test_run_qa_integrity_fail(tmp_path: Path) -> None:
  # 1. Setup paths
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  workspace_dir = tmp_path / "_workspace"

  for d in [metadata_dir, manifest_dir, raw_dir, workspace_dir]:
    d.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  doc_pdf = raw_dir / "doc-1.pdf"
  doc_sha = _write_file(doc_pdf, b"%PDF fake doc")

  # 2. Write archive manifest (matching ds-1 but not doc-1)
  manifest_path = manifest_dir / "archive_manifest.csv"
  manifest_rows = [
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    ),
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1/doc-1",
      resource_kind="documentation_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=doc_sha,
      local_path=str(doc_pdf),
    ),
  ]
  write_archive_manifest(manifest_rows, manifest_path)

  # 3. Write datasets metadata CSV
  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "dataset_id",
      "name",
      "program",
      "category",
      "availability",
      "source_url",
      "local_path",
      "sha256",
      "extraction_notes",
    ])
    writer.writerow([
      "ds-1",
      "Dataset 1",
      "Medicare",
      "Claims",
      "Available",
      "https://resdac.org/cms-data/files/ds-1",
      str(ds_html),
      ds_sha,
      "",
    ])

  # 4. Write documents metadata CSV referencing non-existent dataset 'ds-unmapped'
  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "document_id",
      "dataset_id",
      "title",
      "document_kind",
      "source_url",
      "local_path",
      "sha256",
      "content_type",
      "extraction_notes",
    ])
    writer.writerow([
      "doc-1",
      "ds-unmapped",
      "Doc 1 Title",
      "pdf",
      "https://resdac.org/cms-data/files/ds-1/doc-1",
      str(doc_pdf),
      doc_sha,
      "application/pdf",
      "",
    ])

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=workspace_dir,
  )

  result, _ = run_qa(config)

  # Check references integrity error results in REDO
  assert result.verdict == "redo"
  assert result.error_count == 1
  errors = [f for f in result.findings if f.severity == "error"]
  assert errors[0].field == "dataset_id"
  assert "does not exist in datasets metadata" in errors[0].message


def test_run_qa_validation_failures(tmp_path: Path) -> None:
  # 1. Setup paths
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  workspace_dir = tmp_path / "_workspace"

  for d in [metadata_dir, manifest_dir, raw_dir, workspace_dir]:
    d.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  doc_pdf = raw_dir / "doc-1.pdf"
  doc_sha = _write_file(doc_pdf, b"%PDF fake doc")

  # 2. Write archive manifest (matching correct shas)
  manifest_path = manifest_dir / "archive_manifest.csv"
  manifest_rows = [
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    ),
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1/doc-1",
      resource_kind="documentation_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=doc_sha,
      local_path=str(doc_pdf),
    ),
  ]
  write_archive_manifest(manifest_rows, manifest_path)

  # 3. Write datasets metadata CSV with a checksum mismatch
  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "dataset_id",
      "name",
      "program",
      "category",
      "availability",
      "source_url",
      "local_path",
      "sha256",
      "extraction_notes",
    ])
    writer.writerow([
      "ds-1",
      "Dataset 1",
      "Medicare",
      "Claims",
      "Available",
      "https://resdac.org/cms-data/files/ds-1",
      str(ds_html),
      "wrong-sha-hash",
      "",
    ])

  # 4. Write documents metadata CSV with missing local file
  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
      "document_id",
      "dataset_id",
      "title",
      "document_kind",
      "source_url",
      "local_path",
      "sha256",
      "content_type",
      "extraction_notes",
    ])
    writer.writerow([
      "doc-1",
      "ds-1",
      "Doc 1 Title",
      "pdf",
      "https://resdac.org/cms-data/files/ds-1/doc-1",
      str(raw_dir / "non-existent-doc.pdf"),
      doc_sha,
      "application/pdf",
      "",
    ])

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=workspace_dir,
  )

  result, _ = run_qa(config)

  # Should be FIX since the issues are local file missing and checksum mismatch, and no structural errors.
  # (Wait, if len(errors) <= 5 and no major error field, verdict is fix)
  assert result.verdict == "fix"
  assert result.error_count == 2
  errors = [f for f in result.findings if f.severity == "error"]
  assert any(f.field == "sha256" for f in errors)
  assert any(f.field == "local_path" for f in errors)


def test_run_qa_empty_lists(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  manifest_dir.mkdir(parents=True, exist_ok=True)

  datasets_csv = metadata_dir / "datasets.csv"
  datasets_csv.write_text("dataset_id,name,program,category,availability,source_url,local_path,sha256,extraction_notes\n")

  documents_csv = metadata_dir / "documents.csv"
  documents_csv.write_text("document_id,dataset_id,title,document_kind,source_url,local_path,sha256,content_type,extraction_notes\n")

  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest([], manifest_path)

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_qa(config)
  assert result.verdict == "redo"
  assert result.error_count == 2
  errors = [f for f in result.findings if f.severity == "error"]
  assert any(f.field == "dataset_count" for f in errors)
  assert any(f.field == "document_count" for f in errors)


def test_run_qa_duplicate_ids(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  manifest_dir.mkdir(parents=True, exist_ok=True)
  raw_dir.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest([
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    )
  ], manifest_path)

  # Duplicate ds-1 rows
  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["dataset_id", "name", "program", "category", "availability", "source_url", "local_path", "sha256", "extraction_notes"])
    writer.writerow(["ds-1", "Dataset 1", "Medicare", "Claims", "Available", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, ""])
    writer.writerow(["ds-1", "Dataset 1 Duplicate", "Medicare", "Claims", "Available", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, ""])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["document_id", "dataset_id", "title", "document_kind", "source_url", "local_path", "sha256", "content_type", "extraction_notes"])
    writer.writerow(["doc-1", "ds-1", "Doc 1", "html", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, "text/html", ""])
    # Duplicate doc-1 rows
    writer.writerow(["doc-1", "ds-1", "Doc 1 Duplicate", "html", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, "text/html", ""])

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_qa(config)
  assert result.verdict == "redo"
  assert result.error_count == 2
  errors = [f for f in result.findings if f.severity == "error"]
  assert any("Duplicate dataset_id" in f.message for f in errors)
  assert any("Duplicate document_id" in f.message for f in errors)


def test_run_qa_whitespace_and_failed_archive(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  manifest_dir.mkdir(parents=True, exist_ok=True)
  raw_dir.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest([
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="failed",  # NOT archived
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256="",
      local_path="",
      error="HTTP 404",
    )
  ], manifest_path)

  # ds_id has trailing space: "ds-1 "
  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["dataset_id", "name", "program", "category", "availability", "source_url", "local_path", "sha256", "extraction_notes"])
    writer.writerow(["ds-1 ", "Dataset 1", "Medicare", "Claims", "Available", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, ""])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["document_id", "dataset_id", "title", "document_kind", "source_url", "local_path", "sha256", "content_type", "extraction_notes"])
    writer.writerow(["doc-1", "ds-1", "Doc 1", "html", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, "text/html", ""])

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_qa(config)
  # Should trigger redo due to failed archive state error, and warning due to whitespace
  assert result.verdict == "redo"
  # 2 warnings expected: 1 for whitespace, 1 for missing document edges CSV file
  assert result.warning_count == 2
  assert result.error_count > 0
  assert any("leading/trailing whitespace" in f.message for f in result.findings if f.severity == "warning")
  assert any("archive state is 'failed'" in f.message for f in result.findings if f.severity == "error")


def test_run_qa_corrupted_edges(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  graph_dir = tmp_path / "data" / "graph"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  manifest_dir.mkdir(parents=True, exist_ok=True)
  raw_dir.mkdir(parents=True, exist_ok=True)
  graph_dir.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest([
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    )
  ], manifest_path)

  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["dataset_id", "name", "program", "category", "availability", "source_url", "local_path", "sha256", "extraction_notes"])
    writer.writerow(["ds-1", "Dataset 1", "Medicare", "Claims", "Available", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, ""])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["document_id", "dataset_id", "title", "document_kind", "source_url", "local_path", "sha256", "content_type", "extraction_notes"])
    writer.writerow(["doc-1", "ds-1", "Doc 1", "html", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, "text/html", ""])

  # Corrupt edges CSV content: missing required 'source_id' header column to raise KeyError
  edges_csv = graph_dir / "document_edges.csv"
  edges_csv.write_text("bad_header,target_id,relationship,source_url,local_path,sha256\nds-1,doc-1,has_document,https://resdac.org/cms-data/files/ds-1,local,sha\n")

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    document_edges_path=edges_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_qa(config)
  # Parsing failure on edges is now an ERROR -> verdict is REDO
  assert result.verdict == "redo"
  assert result.error_count == 1
  assert result.findings[0].field == "csv_parsing"


def test_run_qa_validates_ontology_nodes_and_edges(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  manifest_dir = tmp_path / "manifests"
  raw_dir = tmp_path / "data" / "raw"
  graph_dir = tmp_path / "data" / "graph"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  manifest_dir.mkdir(parents=True, exist_ok=True)
  raw_dir.mkdir(parents=True, exist_ok=True)
  graph_dir.mkdir(parents=True, exist_ok=True)

  ds_html = raw_dir / "ds-1.html"
  ds_sha = _write_file(ds_html, b"<html>Dataset</html>")

  manifest_path = manifest_dir / "archive_manifest.csv"
  write_archive_manifest([
    ArchiveManifestRow(
      url="https://resdac.org/cms-data/files/ds-1",
      resource_kind="dataset_page",
      archive_state="archived",
      downloaded_at_utc="2026-06-11T12:00:00Z",
      sha256=ds_sha,
      local_path=str(ds_html),
    )
  ], manifest_path)

  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["dataset_id", "name", "program", "category", "availability", "source_url", "local_path", "sha256", "extraction_notes"])
    writer.writerow(["ds-1", "Dataset 1", "Medicare", "Claims", "Available", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, ""])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["document_id", "dataset_id", "title", "document_kind", "source_url", "local_path", "sha256", "content_type", "extraction_notes"])
    writer.writerow(["doc-1", "ds-1", "Doc 1", "html", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha, "text/html", ""])

  edges_csv = graph_dir / "document_edges.csv"
  with edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["source_id", "target_id", "relationship", "source_url", "local_path", "sha256"])
    writer.writerow(["ds-1", "doc-1", "has_document", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha])

  # Write invalid ontology nodes
  nodes_csv = graph_dir / "ontology_nodes.csv"
  with nodes_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["node_id", "node_class", "name", "source_url", "local_path", "sha256"])
    # Invalid node class "BadClass"
    writer.writerow(["ds-1", "BadClass", "Dataset 1", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha])

  # Write invalid ontology edges
  ontology_edges_csv = graph_dir / "ontology_edges.csv"
  with ontology_edges_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["source_id", "target_id", "relationship", "source_url", "local_path", "sha256"])
    # Invalid source_id "unknown-id"
    writer.writerow(["unknown-id", "ds-1", "belongs_to", "https://resdac.org/cms-data/files/ds-1", str(ds_html), ds_sha])

  config = QAConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    document_edges_path=edges_csv,
    ontology_nodes_path=nodes_csv,
    ontology_edges_path=ontology_edges_csv,
    archive_manifest_path=manifest_path,
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_qa(config)
  assert result.verdict == "redo"
  assert result.error_count == 2

  error_fields = {f.field for f in result.findings if f.severity == "error"}
  assert "node_class" in error_fields
  assert "source_id" in error_fields
