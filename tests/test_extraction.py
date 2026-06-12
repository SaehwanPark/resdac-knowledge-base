from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from cms_kb.archive import ArchiveManifestRow, write_archive_manifest
from cms_kb import extraction
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
      "extraction_notes": "",
    }
  ]


  with (tmp_path / "data" / "metadata" / "documents.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    documents = {row["document_id"]: row for row in csv.DictReader(handle)}
  doc_id = f"pde__data-documentation__{hashlib.sha1(doc_url.encode('utf-8')).hexdigest()[:10]}"
  asset_id = f"pde__codebook-pde_pdf__{hashlib.sha1(asset_url.encode('utf-8')).hexdigest()[:10]}"
  assert documents[doc_id]["dataset_id"] == "pde"
  assert documents[doc_id]["title"] == "PDE Documentation"
  assert documents[asset_id]["document_kind"] == "pdf"
  assert documents[asset_id]["source_url"] == asset_url

  with (tmp_path / "data" / "graph" / "document_edges.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    edges = list(csv.DictReader(handle))
  assert edges == [
    {
      "source_id": "pde",
      "target_id": doc_id,
      "relationship": "has_document",
      "source_url": doc_url,
      "local_path": str(doc_path),
      "sha256": doc_sha,
    },
    {
      "source_id": "pde",
      "target_id": asset_id,
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


def test_run_extraction_reports_documents_without_emitted_dataset(
  tmp_path: Path,
) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  doc_path = tmp_path / "data" / "raw" / "html" / "doc.html"
  listing_asset_path = tmp_path / "data" / "raw" / "assets" / "pdf" / "guide.pdf"
  doc_sha = _write_archive_file(doc_path, b"<html><title>PDE Docs</title></html>")
  listing_asset_sha = _write_archive_file(listing_asset_path, b"%PDF guide")
  _write_manifest(
    [
      ArchiveManifestRow(
        url="https://resdac.org/cms-data/files/pde/data-documentation",
        resource_kind="documentation_page",
        source_url="https://resdac.org/cms-data/files/pde",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256=doc_sha,
        local_path=str(doc_path),
      ),
      ArchiveManifestRow(
        url="https://example.com/guide.pdf",
        resource_kind="asset",
        asset_kind="pdf",
        source_url="https://resdac.org/cms-data?page=0",
        content_type="application/pdf",
        http_status=200,
        archive_state="archived",
        sha256=listing_asset_sha,
        local_path=str(listing_asset_path),
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
  assert {failure.reason for failure in result.failures} == {
    "document references missing dataset",
    "document source is not linked to a dataset page",
  }


def test_run_extraction_resolves_listing_sourced_asset_from_dataset_links(
  tmp_path: Path,
) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  dataset_path = tmp_path / "data" / "raw" / "html" / "dataset.html"
  asset_path = tmp_path / "data" / "raw" / "assets" / "pdf" / "guide.pdf"

  dataset_url = "https://resdac.org/cms-data/files/hha-ffs"
  asset_url = "https://cms.gov/manuals/guide.pdf"
  dataset_body = (
    b"<html><head><title>Home Health Agency</title></head><body>"
    b'<a href="https://cms.gov/manuals/guide.pdf">home health covered services</a>'
    b"</body></html>"
  )
  asset_body = b"%PDF home health guide"
  dataset_sha = _write_archive_file(dataset_path, dataset_body)
  asset_sha = _write_archive_file(asset_path, asset_body)

  _write_manifest(
    [
      ArchiveManifestRow(
        url=dataset_url,
        resource_kind="dataset_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256=dataset_sha,
        local_path=str(dataset_path),
      ),
      ArchiveManifestRow(
        url=asset_url,
        resource_kind="asset",
        asset_kind="pdf",
        source_url="https://resdac.org/cms-data?page=1",
        source_title="Find the CMS Data File You Need | ResDAC",
        content_type="application/pdf",
        http_status=200,
        archive_state="archived",
        sha256=asset_sha,
        local_path=str(asset_path),
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

  assert result.failure_count == 0
  assert result.document_count == 1
  document = result.documents[0]
  assert document.dataset_id == "hha-ffs"
  assert document.source_url == asset_url


def test_run_extraction_keeps_same_basename_assets_distinct(
  tmp_path: Path,
) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  dataset_path = tmp_path / "data" / "raw" / "html" / "dataset.html"
  asset_1_path = tmp_path / "data" / "raw" / "assets" / "pdf" / "one.pdf"
  asset_2_path = tmp_path / "data" / "raw" / "assets" / "pdf" / "two.pdf"
  dataset_url = "https://resdac.org/cms-data/files/pde"
  asset_1_url = "https://example.com/2025/codebook.pdf"
  asset_2_url = "https://example.com/2026/codebook.pdf"
  dataset_sha = _write_archive_file(dataset_path, b"<html><title>PDE</title></html>")
  asset_1_sha = _write_archive_file(asset_1_path, b"%PDF 2025")
  asset_2_sha = _write_archive_file(asset_2_path, b"%PDF 2026")
  _write_manifest(
    [
      ArchiveManifestRow(
        url=dataset_url,
        resource_kind="dataset_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        sha256=dataset_sha,
        local_path=str(dataset_path),
      ),
      ArchiveManifestRow(
        url=asset_1_url,
        resource_kind="asset",
        asset_kind="pdf",
        source_url=dataset_url,
        content_type="application/pdf",
        http_status=200,
        archive_state="archived",
        sha256=asset_1_sha,
        local_path=str(asset_1_path),
      ),
      ArchiveManifestRow(
        url=asset_2_url,
        resource_kind="asset",
        asset_kind="pdf",
        source_url=dataset_url,
        content_type="application/pdf",
        http_status=200,
        archive_state="archived",
        sha256=asset_2_sha,
        local_path=str(asset_2_path),
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

  assert result.document_count == 2
  assert len({row.document_id for row in result.documents}) == 2
  assert all(row.document_id.startswith("pde__codebook_pdf__") for row in result.documents)


def test_extraction_main_returns_nonzero_when_failures_are_present(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  config = ExtractionConfig(
    archive_manifest_path=tmp_path / "manifests" / "archive_manifest.csv",
    metadata_dir=tmp_path / "data" / "metadata",
    graph_dir=tmp_path / "data" / "graph",
    workspace_dir=tmp_path / "_workspace",
  )

  def fake_run_extraction(
    received_config: ExtractionConfig,
  ) -> tuple[extraction.ExtractionResult, Path]:
    return (
      extraction.ExtractionResult(
        config=received_config,
        manifest_rows=1,
        failures=[
          extraction.ExtractionFailure(
            url="https://example.com/missing.pdf",
            resource_kind="asset",
            reason="archived file does not exist",
          )
        ],
      ),
      config.workspace_dir / "04_extraction_pack.md",
    )

  monkeypatch.setattr(extraction, "run_extraction", fake_run_extraction)

  exit_code = extraction.main(
    [
      "--archive-manifest",
      str(config.archive_manifest_path),
      "--metadata-dir",
      str(config.metadata_dir),
      "--graph-dir",
      str(config.graph_dir),
      "--workspace-dir",
      str(config.workspace_dir),
    ]
  )

  assert exit_code == 1


def test_run_extraction_normalizes_fields_and_emits_ontology(tmp_path: Path) -> None:
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  dataset_path = tmp_path / "data" / "raw" / "html" / "dataset.html"

  dataset_body = (
    b"<html><head><title>Part D Event File</title></head><body>"
    b'<div class="views-field views-field-field-program-type">'
    b'<span class="views-label">Program: </span>'
    b'<div class="field-content"><a href="/cms-data?tid_1[1]=1">Medicare</a></div>'
    b"</div>"
    b'<div class="views-field views-field-field-data-file-category">'
    b'<span class="views-label">Category: </span>'
    b'<div class="field-content"><a href="/cms-data?tid[230611]=230611">Special Programs</a></div>'
    b"</div>"
    b'<div class="views-field views-field-field-availability">'
    b'<span class="views-label">Availability: </span>'
    b'<div class="field-content">2016-2025 Q1</div>'
    b"</div>"
    b'<a href="/cms-data/files/cmds-entity">Entity</a>'
    b'<a href="/sites/datadocumentation.resdac.org/files/2022-10/layout.xlsx">Layout</a>'
    b"</body></html>"
  )

  dataset_sha = _write_archive_file(dataset_path, dataset_body)
  dataset_url = "https://resdac.org/cms-data/files/pde"

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

  assert result.dataset_count == 1
  assert result.failures == []

  # Verify datasets.csv output
  with (tmp_path / "data" / "metadata" / "datasets.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    datasets = list(csv.DictReader(handle))
  assert datasets == [
    {
      "dataset_id": "pde",
      "name": "Part D Event File",
      "program": "Medicare",
      "category": "Special Programs",
      "availability": "2016-2025 Q1",
      "source_url": dataset_url,
      "local_path": str(dataset_path),
      "sha256": dataset_sha,
      "extraction_notes": "",
    }
  ]

  # Verify ontology_nodes.csv output
  with (tmp_path / "data" / "graph" / "ontology_nodes.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    nodes = list(csv.DictReader(handle))

  assert len(nodes) == 2
  node_ids = {n["node_id"] for n in nodes}
  assert node_ids == {"pde", "program_medicare"}

  # Verify ontology_edges.csv output
  with (tmp_path / "data" / "graph" / "ontology_edges.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    edges = list(csv.DictReader(handle))

  assert len(edges) == 2
  edge_types = {(e["source_id"], e["target_id"], e["relationship"]) for e in edges}
  assert edge_types == {
    ("pde", "program_medicare", "belongs_to"),
    ("pde", "cmds-entity", "related_to"),
  }
