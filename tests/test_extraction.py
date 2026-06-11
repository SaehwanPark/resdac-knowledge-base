from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from cms_kb.archive import ArchiveManifestRow, write_archive_manifest
from cms_kb.extraction import ExtractionConfig, read_archive_manifest_csv, run_extraction


def _write_archive_file(path: Path, body: bytes) -> str:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(body)
  return hashlib.sha256(body).hexdigest()


def _write_manifest(rows: list[ArchiveManifestRow], path: Path) -> None:
  write_archive_manifest(rows, path)


def test_read_archive_manifest_csv_rejects_missing_columns(tmp_path: Path) -> None:
  input_path = tmp_path / "archive_manifest.csv"
  input_path.write_text("url,archive_state\nhttps://example.com,archived\n")

  with pytest.raises(ValueError, match="missing required columns"):
    read_archive_manifest_csv(input_path)


def test_run_extraction_writes_dataset_document_and_graph_outputs(
  tmp_path: Path,
) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  dataset_path = tmp_path / "data" / "raw" / "html" / "dataset.html"
  doc_path = tmp_path / "data" / "raw" / "html" / "doc.html"
  asset_path = tmp_path / "data" / "raw" / "assets" / "pdf" / "codebook.pdf"

  dataset_body = b"<html><head><title>Part D Event File</title></head><body></body></html>"
  doc_body = b"<html><head><title>PDE Documentation</title></head><body></body></html>"
  asset_body = b"%PDF-1.4 fake codebook"

  dataset_sha = _write_archive_file(dataset_path, dataset_body)
  doc_sha = _write_archive_file(doc_path, doc_body)
  asset_sha = _write_archive_file(asset_path, asset_body)

  dataset_url = "https://resdac.org/cms-data/files/pde"
  doc_url = "https://resdac.org/cms-data/files/pde/data-documentation"
  asset_url = "https://example.com/codebook-pde.pdf"
  _write_manifest(
    [
      ArchiveManifestRow(
        url=dataset_url,
        resource_kind="dataset_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        downloaded_at_utc="2026-06-11T12:00:00Z",
        sha256=dataset_sha,
        local_path=str(dataset_path),
      ),
      ArchiveManifestRow(
        url=doc_url,
        resource_kind="documentation_page",
        source_url=dataset_url,
        source_title="Part D Event File",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        downloaded_at_utc="2026-06-11T12:00:00Z",
        sha256=doc_sha,
        local_path=str(doc_path),
      ),
      ArchiveManifestRow(
        url=asset_url,
        resource_kind="asset",
        asset_kind="pdf",
        source_url=doc_url,
        source_title="PDE Documentation",
        content_type="application/pdf",
        http_status=200,
        archive_state="archived",
        downloaded_at_utc="2026-06-11T12:00:00Z",
        sha256=asset_sha,
        local_path=str(asset_path),
      ),
    ],
    manifest_path,
  )

  result, summary_path = run_extraction(
    ExtractionConfig(
      archive_manifest_path=manifest_path,
      metadata_dir=tmp_path / "data" / "metadata",
      graph_dir=tmp_path / "data" / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.dataset_count == 1
  assert result.document_count == 2
  assert result.edge_count == 2
  assert result.failure_count == 0

  with (tmp_path / "data" / "metadata" / "datasets.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    datasets = list(csv.DictReader(handle))
  assert datasets == [
    {
      "dataset_id": "pde",
      "name": "Part D Event File",
      "program": "",
      "category": "",
      "availability": "",
      "source_url": dataset_url,
      "local_path": str(dataset_path),
      "sha256": dataset_sha,
      "extraction_notes": "program, category, and availability not normalized",
    }
  ]

  with (tmp_path / "data" / "metadata" / "documents.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    documents = {row["document_id"]: row for row in csv.DictReader(handle)}
  assert documents["pde__data-documentation"]["dataset_id"] == "pde"
  assert documents["pde__data-documentation"]["title"] == "PDE Documentation"
  assert documents["pde__codebook-pde_pdf"]["document_kind"] == "pdf"
  assert documents["pde__codebook-pde_pdf"]["source_url"] == asset_url

  with (tmp_path / "data" / "graph" / "document_edges.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    edges = list(csv.DictReader(handle))
  assert edges == [
    {
      "source_id": "pde",
      "target_id": "pde__data-documentation",
      "relationship": "has_document",
      "source_url": doc_url,
      "local_path": str(doc_path),
      "sha256": doc_sha,
    },
    {
      "source_id": "pde",
      "target_id": "pde__codebook-pde_pdf",
      "relationship": "has_document",
      "source_url": asset_url,
      "local_path": str(asset_path),
      "sha256": asset_sha,
    },
  ]

  summary_text = summary_path.read_text(encoding="utf-8")
  assert "- Datasets: 1" in summary_text
  assert "- Documents: 2" in summary_text
  assert "- Failures: 0" in summary_text


def test_run_extraction_skips_non_eligible_rows(tmp_path: Path) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  listing_path = tmp_path / "data" / "raw" / "html" / "listing.html"
  listing_sha = _write_archive_file(listing_path, b"<html></html>")
  _write_manifest(
    [
      ArchiveManifestRow(
        url="https://resdac.org/cms-data?page=0",
        resource_kind="listing_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256=listing_sha,
        local_path=str(listing_path),
      ),
      ArchiveManifestRow(
        url="https://example.com/dead.pdf",
        resource_kind="asset",
        asset_kind="pdf",
        archive_state="failed",
        error="HTTP Error 503",
      ),
    ],
    manifest_path,
  )

  result, _ = run_extraction(
    ExtractionConfig(
      archive_manifest_path=manifest_path,
      metadata_dir=tmp_path / "data" / "metadata",
      graph_dir=tmp_path / "data" / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.dataset_count == 0
  assert result.document_count == 0
  assert result.edge_count == 0
  assert result.failure_count == 0


def test_run_extraction_reports_missing_file_and_checksum_mismatch(
  tmp_path: Path,
) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  mismatch_path = tmp_path / "data" / "raw" / "html" / "dataset.html"
  _write_archive_file(mismatch_path, b"<html><title>PDE</title></html>")
  _write_manifest(
    [
      ArchiveManifestRow(
        url="https://resdac.org/cms-data/files/pde",
        resource_kind="dataset_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256="0" * 64,
        local_path=str(mismatch_path),
      ),
      ArchiveManifestRow(
        url="https://resdac.org/cms-data/files/mbsf",
        resource_kind="dataset_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256="1" * 64,
        local_path=str(tmp_path / "missing.html"),
      ),
    ],
    manifest_path,
  )

  result, summary_path = run_extraction(
    ExtractionConfig(
      archive_manifest_path=manifest_path,
      metadata_dir=tmp_path / "data" / "metadata",
      graph_dir=tmp_path / "data" / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.failure_count == 2
  assert {failure.reason for failure in result.failures} == {
    "checksum mismatch",
    "archived file does not exist",
  }
  assert result.dataset_count == 0
  summary_text = summary_path.read_text(encoding="utf-8")
  assert "checksum mismatch" in summary_text
  assert "archived file does not exist" in summary_text
