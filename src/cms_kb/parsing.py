"""Phase 3 document parsing and text chunking for CMS KB."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field

# Try standard fitz import for PyMuPDF
try:
  import fitz  # type: ignore
except ImportError:
  import pymupdf as fitz  # type: ignore

import trafilatura

from .extraction import DatasetMetadataRow, DocumentMetadataRow


class ParsingConfig(BaseModel):
  datasets_metadata_path: Path = Path("data/metadata/datasets.csv")
  documents_metadata_path: Path = Path("data/metadata/documents.csv")
  parsed_root: Path = Path("data/parsed")
  workspace_dir: Path = Path("_workspace")
  chunk_size: int = 500
  chunk_overlap: int = 100


class ChunkMetadata(BaseModel):
  chunk_id: str
  source_document: str
  page: int | None = None
  text: str
  dataset: str
  url: str


class ParsingFailure(BaseModel):
  url: str
  local_path: str = ""
  reason: str


class ParsingResult(BaseModel):
  config: ParsingConfig
  parsed_datasets_count: int = 0
  parsed_documents_count: int = 0
  chunks_count: int = 0
  failures: list[ParsingFailure] = Field(default_factory=list)

  @property
  def failure_count(self) -> int:
    return len(self.failures)


def read_datasets_csv(input_path: Path) -> list[DatasetMetadataRow]:
  if not input_path.exists():
    return []
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
  if not input_path.exists():
    return []
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


def parse_html(local_path: Path) -> str:
  with local_path.open("r", encoding="utf-8", errors="replace") as f:
    html_content = f.read()
  # extract body text using trafilatura
  text = trafilatura.extract(
    html_content, no_fallback=False, include_comments=False, include_tables=True
  )
  return text or ""


def parse_pdf(local_path: Path) -> list[tuple[int, str]]:
  doc = fitz.open(str(local_path))
  pages: list[tuple[int, str]] = []
  for page_idx in range(len(doc)):
    page = doc.load_page(page_idx)
    text = page.get_text()
    text_str = text if isinstance(text, str) else ""
    pages.append((page_idx + 1, text_str))
  doc.close()
  return pages


def chunk_text(
  text: str,
  chunk_size: int = 500,
  chunk_overlap: int = 100,
) -> list[str]:
  if not text or not text.strip():
    return []

  text = re.sub(r"\s+", " ", text).strip()
  if len(text) <= chunk_size:
    return [text]

  chunks: list[str] = []
  start = 0
  text_len = len(text)

  while start < text_len:
    end = start + chunk_size
    if end >= text_len:
      chunks.append(text[start:])
      break

    # Look back for a word boundary (space) to avoid cutting words
    search_start = max(start, start + chunk_size - 30)
    space_idx = text.rfind(" ", search_start, end)
    if space_idx != -1 and space_idx > start:
      end = space_idx

    chunks.append(text[start:end].strip())
    next_start = end - chunk_overlap
    if next_start <= start:
      start = end
    else:
      start = next_start

  return [c for c in chunks if c.strip()]


def write_parsing_workspace_summary(result: ParsingResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "05_parsing_pack.md"
  lines = [
    "# Parsing Pack",
    "",
    f"- Datasets metadata path: {result.config.datasets_metadata_path}",
    f"- Documents metadata path: {result.config.documents_metadata_path}",
    f"- Datasets parsed: {result.parsed_datasets_count}",
    f"- Documents parsed: {result.parsed_documents_count}",
    f"- Chunks generated: {result.chunks_count}",
    f"- Failures: {result.failure_count}",
    "",
    "## Outputs",
    "",
    f"- Parsed HTML directory: {result.config.parsed_root / 'html'}",
    f"- Parsed PDF directory: {result.config.parsed_root / 'pdf'}",
    f"- Chunks directory: {result.config.parsed_root / 'chunks'}",
    f"- Unified chunks file: {result.config.parsed_root / 'chunks.jsonl'}",
    "",
    "## Failures",
    "",
  ]
  if result.failures:
    lines.extend(["| url | local_path | reason |", "| --- | --- | --- |"])
    for failure in result.failures[:25]:
      lines.append(
        f"| {failure.url} | {failure.local_path} | {failure.reason} |"
      )
    if len(result.failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(result.failures) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_parsing(config: ParsingConfig) -> tuple[ParsingResult, Path]:
  datasets = read_datasets_csv(config.datasets_metadata_path)
  documents = read_documents_csv(config.documents_metadata_path)

  # Setup output directories
  html_out = config.parsed_root / "html"
  pdf_out = config.parsed_root / "pdf"
  chunks_out = config.parsed_root / "chunks"

  html_out.mkdir(parents=True, exist_ok=True)
  pdf_out.mkdir(parents=True, exist_ok=True)
  chunks_out.mkdir(parents=True, exist_ok=True)

  parsed_datasets_count = 0
  parsed_documents_count = 0
  chunks: list[ChunkMetadata] = []
  failures: list[ParsingFailure] = []

  # 1. Parse Datasets (all are HTML files)
  for dataset in datasets:
    local_path = Path(dataset.local_path)
    if not local_path.exists():
      failures.append(
        ParsingFailure(
          url=dataset.source_url,
          local_path=dataset.local_path,
          reason="dataset file does not exist locally",
        )
      )
      continue

    try:
      text = parse_html(local_path)
      if not text:
        failures.append(
          ParsingFailure(
            url=dataset.source_url,
            local_path=dataset.local_path,
            reason="extracted HTML text is empty",
          )
        )
        continue

      # Save clean raw text
      txt_path = html_out / f"{dataset.dataset_id}.txt"
      txt_path.write_text(text, encoding="utf-8")
      parsed_datasets_count += 1

      # Chunk text
      txt_chunks = chunk_text(
        text,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
      )
      for idx, chunk_txt in enumerate(txt_chunks):
        chunk_id = f"{dataset.dataset_id}__chunk_{idx}"
        chunk = ChunkMetadata(
          chunk_id=chunk_id,
          source_document=dataset.local_path,
          page=1,
          text=chunk_txt,
          dataset=dataset.dataset_id,
          url=dataset.source_url,
        )
        chunks.append(chunk)

        # Save individual chunk
        chunk_path = chunks_out / f"{chunk_id}.json"
        chunk_path.write_text(
          chunk.model_dump_json(indent=2), encoding="utf-8"
        )

    except Exception as exc:
      failures.append(
        ParsingFailure(
          url=dataset.source_url,
          local_path=dataset.local_path,
          reason=f"failed to parse/chunk dataset page: {exc}",
        )
      )

  # 2. Parse Documents (can be HTML or PDF)
  for doc in documents:
    local_path = Path(doc.local_path)
    if not local_path.exists():
      failures.append(
        ParsingFailure(
          url=doc.source_url,
          local_path=doc.local_path,
          reason="document file does not exist locally",
        )
      )
      continue

    try:
      if doc.document_kind == "pdf":
        pages = parse_pdf(local_path)
        if not pages:
          failures.append(
            ParsingFailure(
              url=doc.source_url,
              local_path=doc.local_path,
              reason="extracted PDF pages are empty",
            )
          )
          continue

        # Save combined clean text
        combined_text = "\n\n".join(text for _, text in pages)
        txt_path = pdf_out / f"{doc.document_id}.txt"
        txt_path.write_text(combined_text, encoding="utf-8")
        parsed_documents_count += 1

        # Chunk text page-by-page
        for page_num, page_text in pages:
          page_chunks = chunk_text(
            page_text,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
          )
          for idx, chunk_txt in enumerate(page_chunks):
            chunk_id = f"{doc.document_id}__p{page_num}__chunk_{idx}"
            chunk = ChunkMetadata(
              chunk_id=chunk_id,
              source_document=doc.local_path,
              page=page_num,
              text=chunk_txt,
              dataset=doc.dataset_id,
              url=doc.source_url,
            )
            chunks.append(chunk)

            # Save individual chunk
            chunk_path = chunks_out / f"{chunk_id}.json"
            chunk_path.write_text(
              chunk.model_dump_json(indent=2), encoding="utf-8"
            )

      else:
        # Assume HTML
        text = parse_html(local_path)
        if not text:
          failures.append(
            ParsingFailure(
              url=doc.source_url,
              local_path=doc.local_path,
              reason="extracted HTML text is empty",
            )
          )
          continue

        # Save clean raw text
        txt_path = html_out / f"{doc.document_id}.txt"
        txt_path.write_text(text, encoding="utf-8")
        parsed_documents_count += 1

        # Chunk text
        txt_chunks = chunk_text(
          text,
          chunk_size=config.chunk_size,
          chunk_overlap=config.chunk_overlap,
        )
        for idx, chunk_txt in enumerate(txt_chunks):
          chunk_id = f"{doc.document_id}__chunk_{idx}"
          chunk = ChunkMetadata(
            chunk_id=chunk_id,
            source_document=doc.local_path,
            page=1,
            text=chunk_txt,
            dataset=doc.dataset_id,
            url=doc.source_url,
          )
          chunks.append(chunk)

          # Save individual chunk
          chunk_path = chunks_out / f"{chunk_id}.json"
          chunk_path.write_text(
            chunk.model_dump_json(indent=2), encoding="utf-8"
          )

    except Exception as exc:
      failures.append(
        ParsingFailure(
          url=doc.source_url,
          local_path=doc.local_path,
          reason=f"failed to parse/chunk document: {exc}",
        )
      )

  # Write consolidated chunks.jsonl
  jsonl_path = config.parsed_root / "chunks.jsonl"
  with jsonl_path.open("w", encoding="utf-8") as f:
    for chunk in chunks:
      f.write(chunk.model_dump_json() + "\n")

  result = ParsingResult(
    config=config,
    parsed_datasets_count=parsed_datasets_count,
    parsed_documents_count=parsed_documents_count,
    chunks_count=len(chunks),
    failures=failures,
  )

  summary_path = write_parsing_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Parse archived HTML/PDF files and extract metadata chunks."
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
  parser.add_argument("--parsed-root", type=Path, default=Path("data/parsed"))
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  parser.add_argument("--chunk-size", type=int, default=500)
  parser.add_argument("--chunk-overlap", type=int, default=100)
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = ParsingConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    parsed_root=args.parsed_root,
    workspace_dir=args.workspace_dir,
    chunk_size=args.chunk_size,
    chunk_overlap=args.chunk_overlap,
  )
  try:
    result, summary_path = run_parsing(config)
    print(
      f"wrote {result.parsed_datasets_count} parsed datasets, "
      f"{result.parsed_documents_count} parsed documents, "
      f"and {result.chunks_count} chunks to {config.parsed_root}; "
      f"summary: {summary_path}"
    )
    return 1 if result.failure_count else 0
  except Exception as exc:
    print(f"Error executing parsing: {exc}", file=sys.stderr)
    return 1


__all__ = [
  "ChunkMetadata",
  "ParsingConfig",
  "ParsingFailure",
  "ParsingResult",
  "build_arg_parser",
  "chunk_text",
  "main",
  "parse_html",
  "parse_pdf",
  "run_parsing",
]
