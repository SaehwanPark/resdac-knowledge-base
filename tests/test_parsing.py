from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

# Try standard fitz import
try:
  import fitz  # type: ignore
except ImportError:
  import pymupdf as fitz  # type: ignore

from cms_kb.parsing import (
  ParsingConfig,
  chunk_text,
  main,
  parse_html,
  parse_pdf,
  run_parsing,
)


def test_chunk_text_empty_and_short() -> None:
  assert chunk_text("") == []
  assert chunk_text("   ") == []

  short_text = "This is a short text."
  assert chunk_text(short_text, chunk_size=50, chunk_overlap=10) == [short_text]


def test_chunk_text_invalid_settings() -> None:
  with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
    chunk_text("test", chunk_size=0)

  with pytest.raises(ValueError, match="chunk_overlap must be non-negative"):
    chunk_text("test", chunk_size=10, chunk_overlap=-1)

  with pytest.raises(
    ValueError, match="chunk_overlap must be less than chunk_size"
  ):
    chunk_text("test", chunk_size=10, chunk_overlap=10)


def test_pydantic_config_validation() -> None:
  with pytest.raises(ValidationError):
    ParsingConfig(chunk_size=0)

  with pytest.raises(ValidationError):
    ParsingConfig(chunk_size=10, chunk_overlap=-1)

  with pytest.raises(ValidationError):
    ParsingConfig(chunk_size=10, chunk_overlap=10)


def test_chunk_text_splits_at_space_boundary() -> None:
  text = "This is a sentence that is longer than chunk size."
  chunks = chunk_text(text, chunk_size=20, chunk_overlap=5)
  assert chunks[0] == "This is a sentence"
  assert len(chunks) > 1
  for chunk in chunks:
    assert len(chunk) <= 20
    assert chunk.strip() != ""


def test_parse_html(tmp_path: Path) -> None:
  html_file = tmp_path / "test.html"
  html_file.write_text(
    "<html><body><p>Hello World!</p><p>This is clean text.</p></body></html>",
    encoding="utf-8",
  )
  text = parse_html(html_file)
  assert "Hello World!" in text
  assert "This is clean text." in text


def test_parse_pdf(tmp_path: Path) -> None:
  pdf_path = tmp_path / "test.pdf"

  # Create a simple PDF using PyMuPDF dynamically
  doc = fitz.open()
  page1 = doc.new_page()
  page1.insert_text((50, 50), "Hello on Page 1")

  page2 = doc.new_page()
  page2.insert_text((50, 50), "Hello on Page 2")

  doc.save(str(pdf_path))
  doc.close()

  pages = parse_pdf(pdf_path)
  assert len(pages) == 2
  assert pages[0][0] == 1
  assert "Page 1" in pages[0][1]
  assert pages[1][0] == 2
  assert "Page 2" in pages[1][1]


def test_run_parsing_success_flow(tmp_path: Path) -> None:
  # 1. Create directories
  raw_root = tmp_path / "data" / "raw"
  html_raw_dir = raw_root / "html"
  asset_raw_dir = raw_root / "assets" / "pdf"

  html_raw_dir.mkdir(parents=True, exist_ok=True)
  asset_raw_dir.mkdir(parents=True, exist_ok=True)

  metadata_dir = tmp_path / "data" / "metadata"
  metadata_dir.mkdir(parents=True, exist_ok=True)

  workspace_dir = tmp_path / "_workspace"
  workspace_dir.mkdir(parents=True, exist_ok=True)

  # 2. Write raw files
  dataset_html = html_raw_dir / "ds-slug.html"
  dataset_html.write_text(
    "<html><body><main>Dataset Page Content</main></body></html>",
    encoding="utf-8",
  )

  doc_pdf = asset_raw_dir / "doc-slug.pdf"
  doc = fitz.open()
  p = doc.new_page()
  p.insert_text((50, 50), "Document PDF Content Page One")
  doc.save(str(doc_pdf))
  doc.close()

  # 3. Write metadata CSV files
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
      "ds-slug",
      "Dataset Name",
      "Program",
      "Category",
      "Available",
      "https://example.com/ds-slug",
      str(dataset_html),
      "fake-sha",
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
      "ds-slug__doc-slug",
      "ds-slug",
      "Doc Title",
      "pdf",
      "https://example.com/doc-slug.pdf",
      str(doc_pdf),
      "fake-sha-2",
      "application/pdf",
      "",
    ])

  # 4. Execute parsing
  config = ParsingConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    parsed_root=tmp_path / "data" / "parsed",
    workspace_dir=workspace_dir,
    chunk_size=100,
    chunk_overlap=10,
  )

  result, summary_path = run_parsing(config)

  # 5. Assert results
  assert result.parsed_datasets_count == 1
  assert result.parsed_documents_count == 1
  assert result.failure_count == 0
  assert result.chunks_count > 0

  # Check text files generated
  assert (config.parsed_root / "html" / "ds-slug.txt").exists()
  assert (config.parsed_root / "pdf" / "ds-slug__doc-slug.txt").exists()

  # Check chunks output
  assert (config.parsed_root / "chunks.jsonl").exists()
  assert summary_path.exists()

  # Validate one chunk
  with (config.parsed_root / "chunks.jsonl").open("r", encoding="utf-8") as f:
    first_chunk = json.loads(f.readline())
    assert "chunk_id" in first_chunk
    assert first_chunk["dataset"] == "ds-slug"
    assert first_chunk["text"] != ""
    assert first_chunk["page"] is None  # HTML page should be None


def test_run_parsing_rejects_unsafe_output_ids(tmp_path: Path) -> None:
  raw_root = tmp_path / "data" / "raw"
  raw_root.mkdir(parents=True, exist_ok=True)
  dataset_html = raw_root / "dataset.html"
  dataset_html.write_text(
    "<html><body><main>Dataset Page Content</main></body></html>",
    encoding="utf-8",
  )

  metadata_dir = tmp_path / "data" / "metadata"
  metadata_dir.mkdir(parents=True, exist_ok=True)

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
      "../outside",
      "Dataset Name",
      "Program",
      "Category",
      "Available",
      "https://example.com/ds",
      str(dataset_html),
      "fake-sha",
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

  config = ParsingConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    parsed_root=tmp_path / "data" / "parsed",
    workspace_dir=tmp_path / "_workspace",
  )

  result, _ = run_parsing(config)

  assert result.failure_count == 1
  assert "dataset_id contains unsafe output path characters" in result.failures[0].reason
  assert not (tmp_path / "data" / "outside.txt").exists()


def test_missing_metadata_files(tmp_path: Path) -> None:
  config = ParsingConfig(
    datasets_metadata_path=tmp_path / "missing_datasets.csv",
    documents_metadata_path=tmp_path / "missing_documents.csv",
    parsed_root=tmp_path / "data" / "parsed",
    workspace_dir=tmp_path / "_workspace",
  )
  with pytest.raises(FileNotFoundError):
    run_parsing(config)


def test_run_parsing_failures(tmp_path: Path) -> None:
  metadata_dir = tmp_path / "data" / "metadata"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  workspace_dir = tmp_path / "_workspace"
  workspace_dir.mkdir(parents=True, exist_ok=True)

  # 1. Scanned PDF (empty text)
  empty_pdf = tmp_path / "empty.pdf"
  doc = fitz.open()
  doc.new_page()  # Blank page
  doc.save(str(empty_pdf))
  doc.close()

  # 2. Write metadata CSV with failures:
  # - ds1: missing local file
  # - ds2: empty local path
  # - doc1: unmapped dataset ID (missing from datasets)
  # - doc2: unsupported document kind
  # - doc3: scanned PDF (empty text)
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
      "ds-slug",
      "DS",
      "",
      "",
      "",
      "https://example.com/ds",
      str(tmp_path / "missing.html"),
      "hash",
      "",
    ])
    writer.writerow([
      "ds-slug-empty",
      "DS Empty",
      "",
      "",
      "",
      "https://example.com/ds-empty",
      "",
      "hash",
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
    # doc1: unmapped dataset ID (e.g. unmapped-ds)
    writer.writerow([
      "doc1",
      "unmapped-ds",
      "Unmapped",
      "pdf",
      "https://example.com/doc1",
      str(empty_pdf),
      "hash",
      "application/pdf",
      "",
    ])
    # doc2: unsupported document kind
    writer.writerow([
      "doc2",
      "ds-slug",
      "Unsupported",
      "xlsx",
      "https://example.com/doc2",
      str(empty_pdf),
      "hash",
      "xlsx",
      "",
    ])
    # doc3: scanned PDF
    writer.writerow([
      "doc3",
      "ds-slug",
      "Scanned",
      "pdf",
      "https://example.com/doc3",
      str(empty_pdf),
      "hash",
      "application/pdf",
      "",
    ])

  config = ParsingConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    parsed_root=tmp_path / "data" / "parsed",
    workspace_dir=workspace_dir,
  )

  result, summary_path = run_parsing(config)

  assert result.parsed_datasets_count == 0
  assert result.parsed_documents_count == 0
  assert result.failure_count == 5

  # Verify specific failure reasons
  reasons = [f.reason for f in result.failures]
  assert any("does not exist locally" in r for r in reasons)
  assert any("empty local path" in r for r in reasons)
  assert any("not found in datasets metadata" in r for r in reasons)
  assert any("unsupported document kind" in r for r in reasons)
  assert any("scanned images" in r for r in reasons)

  # Check that main CLI returns 1 on parsing failures
  exit_code = main([
    "--datasets-metadata",
    str(datasets_csv),
    "--documents-metadata",
    str(documents_csv),
    "--parsed-root",
    str(tmp_path / "data" / "parsed-cli"),
    "--workspace-dir",
    str(workspace_dir),
  ])
  assert exit_code == 1
