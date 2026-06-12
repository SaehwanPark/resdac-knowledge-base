from __future__ import annotations

import csv
import json
from pathlib import Path

# Try standard fitz import
try:
  import fitz  # type: ignore
except ImportError:
  import pymupdf as fitz  # type: ignore

from cms_kb.parsing import (
  ParsingConfig,
  chunk_text,
  parse_html,
  parse_pdf,
  run_parsing,
)


def test_chunk_text_empty_and_short() -> None:
  assert chunk_text("") == []
  assert chunk_text("   ") == []

  short_text = "This is a short text."
  assert chunk_text(short_text, chunk_size=50) == [short_text]


def test_chunk_text_splits_at_space_boundary() -> None:
  # Size is 20. "This is a sentence that is longer than chunk size."
  # 20 chars from start is "This is a sentence t" (length 20).
  # The space before "t" is after "sentence" at index 17.
  # So it should split at "This is a sentence".
  text = "This is a sentence that is longer than chunk size."
  chunks = chunk_text(text, chunk_size=20, chunk_overlap=5)
  assert chunks[0] == "This is a sentence"
  # Overlap 5: search from end of first chunk (index 18) minus 5 = 13.
  # "sentence" starts at index 10.
  # Overlapping segment "tence" or space-aligned boundary.
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
