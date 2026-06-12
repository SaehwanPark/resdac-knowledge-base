"""Phase 3 document parsing and text chunking for CMS KB."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import zipfile
from xml.etree import ElementTree
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

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

  @model_validator(mode="after")
  def validate_chunk_settings(self) -> ParsingConfig:
    if self.chunk_size <= 0:
      raise ValueError("chunk_size must be greater than 0")
    if self.chunk_overlap < 0:
      raise ValueError("chunk_overlap must be non-negative")
    if self.chunk_overlap >= self.chunk_size:
      raise ValueError("chunk_overlap must be less than chunk_size")
    return self


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


SAFE_OUTPUT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _safe_output_id_error(field: str, value: str) -> str:
  if not value.strip():
    return f"{field} must not be empty"
  if (
    value != Path(value).name
    or Path(value).is_absolute()
    or ".." in Path(value).parts
    or not SAFE_OUTPUT_ID_PATTERN.fullmatch(value)
  ):
    return f"{field} contains unsafe output path characters: {value}"
  return ""


def read_datasets_csv(input_path: Path) -> list[DatasetMetadataRow]:
  # Let FileNotFoundError propagate if the file is missing
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
  # Let FileNotFoundError propagate if the file is missing
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
  pages: list[tuple[int, str]] = []
  with fitz.open(str(local_path)) as doc:
    for page_idx in range(len(doc)):
      page = doc.load_page(page_idx)
      text = page.get_text()
      text_str = text if isinstance(text, str) else ""
      pages.append((page_idx + 1, text_str))
  return pages


def _xml_text(element: ElementTree.Element) -> str:
  return "".join(element.itertext())


def _read_xlsx_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
  if "xl/sharedStrings.xml" not in workbook.namelist():
    return []

  root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
  shared_strings: list[str] = []
  for item in root:
    shared_strings.append(_xml_text(item).strip())
  return shared_strings


def _xlsx_cell_text(
  cell: ElementTree.Element, shared_strings: list[str]
) -> str:
  cell_type = cell.attrib.get("t", "")
  if cell_type == "inlineStr":
    inline_text = cell.find("{*}is")
    return _xml_text(inline_text).strip() if inline_text is not None else ""

  value = cell.find("{*}v")
  if value is None or value.text is None:
    return ""

  raw_value = value.text.strip()
  if cell_type == "s":
    try:
      return shared_strings[int(raw_value)]
    except (IndexError, ValueError):
      return raw_value
  return raw_value


def _xlsx_sheet_sort_key(path: str) -> tuple[int, str]:
  match = re.search(r"sheet(\d+)\.xml$", path)
  if match is None:
    return (0, path)
  return (int(match.group(1)), path)


def parse_xlsx(local_path: Path) -> list[tuple[int, str]]:
  sheets: list[tuple[int, str]] = []
  with zipfile.ZipFile(local_path) as workbook:
    shared_strings = _read_xlsx_shared_strings(workbook)
    sheet_paths = sorted(
      [
        name
        for name in workbook.namelist()
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
      ],
      key=_xlsx_sheet_sort_key,
    )

    for sheet_index, sheet_path in enumerate(sheet_paths, start=1):
      root = ElementTree.fromstring(workbook.read(sheet_path))
      rows: list[str] = []
      for row in root.findall(".//{*}sheetData/{*}row"):
        values = [
          _xlsx_cell_text(cell, shared_strings)
          for cell in row.findall("{*}c")
        ]
        row_text = "\t".join(value for value in values if value)
        if row_text.strip():
          rows.append(row_text)
      sheets.append((sheet_index, "\n".join(rows)))
  return sheets


def chunk_text(
  text: str,
  chunk_size: int = 500,
  chunk_overlap: int = 100,
) -> list[str]:
  if chunk_size <= 0:
    raise ValueError("chunk_size must be greater than 0")
  if chunk_overlap < 0:
    raise ValueError("chunk_overlap must be non-negative")
  if chunk_overlap >= chunk_size:
    raise ValueError("chunk_overlap must be less than chunk_size")

  if not text or not text.strip():
    return []

  # Normalize horizontal spaces but keep paragraph/newline spacing
  text = re.sub(r"[ \t]+", " ", text)
  text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

  if len(text) <= chunk_size:
    return [text]

  chunks: list[str] = []
  start = 0
  text_len = len(text)

  while start < text_len:
    if start + chunk_size >= text_len:
      chunks.append(text[start:].strip())
      break

    end = start + chunk_size

    # Look back for a word boundary (space) near the end to avoid cutting words
    search_start = max(start, end - 30)
    space_idx = text.rfind(" ", search_start, end)
    if space_idx != -1 and space_idx > start:
      end = space_idx

    chunks.append(text[start:end].strip())

    # Align the start of the next overlapping chunk to the nearest word boundary
    next_start = end - chunk_overlap
    if next_start < text_len:
      search_overlap_start = max(start, next_start - 15)
      space_overlap_idx = text.find(" ", search_overlap_start, next_start + 15)
      if space_overlap_idx != -1 and space_overlap_idx > start:
        next_start = space_overlap_idx + 1

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
    f"- Parsed XLSX directory: {result.config.parsed_root / 'xlsx'}",
    f"- Chunks directory: {result.config.parsed_root / 'chunks'}",
    f"- Unified chunks file: {result.config.parsed_root / 'chunks.jsonl'}",
    "",
    "## Failures",
    "",
  ]
  if result.failures:
    lines.extend(["| url | local_path | reason |", "| --- | --- | --- |"])
    for failure in result.failures[:25]:
      # Escape pipe characters and replace newlines to avoid breaking markdown tables
      reason_safe = failure.reason.replace("|", "\\|").replace("\n", " ")
      lines.append(
        f"| {failure.url} | {failure.local_path} | {reason_safe} |"
      )
    if len(result.failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(result.failures) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_parsing(config: ParsingConfig) -> tuple[ParsingResult, Path]:
  # Let FileNotFoundError propagate
  datasets = read_datasets_csv(config.datasets_metadata_path)
  documents = read_documents_csv(config.documents_metadata_path)

  # Setup output directories (clean them first to prevent orphaned files)
  html_out = config.parsed_root / "html"
  pdf_out = config.parsed_root / "pdf"
  xlsx_out = config.parsed_root / "xlsx"
  chunks_out = config.parsed_root / "chunks"

  for path in [html_out, pdf_out, xlsx_out, chunks_out]:
    if path.exists():
      shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

  parsed_datasets_count = 0
  parsed_documents_count = 0
  chunks_count = 0
  failures: list[ParsingFailure] = []

  valid_dataset_ids = {d.dataset_id for d in datasets}
  jsonl_path = config.parsed_root / "chunks.jsonl"

  with jsonl_path.open("w", encoding="utf-8") as f_jsonl:
    # 1. Parse Datasets (all are HTML files)
    for dataset in datasets:
      dataset_id_error = _safe_output_id_error("dataset_id", dataset.dataset_id)
      if dataset_id_error:
        failures.append(
          ParsingFailure(
            url=dataset.source_url,
            local_path=dataset.local_path,
            reason=dataset_id_error,
          )
        )
        continue

      local_path_str = dataset.local_path.strip()
      if not local_path_str:
        failures.append(
          ParsingFailure(
            url=dataset.source_url,
            local_path="",
            reason="dataset has empty local path",
          )
        )
        continue

      local_path = Path(local_path_str)
      if not local_path.is_file():
        failures.append(
          ParsingFailure(
            url=dataset.source_url,
            local_path=local_path_str,
            reason="dataset file does not exist locally",
          )
        )
        continue

      try:
        text = parse_html(local_path)
        if not text or not text.strip():
          failures.append(
            ParsingFailure(
              url=dataset.source_url,
              local_path=local_path_str,
              reason="extracted HTML text is empty",
            )
          )
          continue

        # Save clean raw text
        txt_path = html_out / f"{dataset.dataset_id}.txt"
        txt_path.write_text(text, encoding="utf-8")
        parsed_datasets_count += 1

        # Chunk text (page = None for HTML)
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
            page=None,
            text=chunk_txt,
            dataset=dataset.dataset_id,
            url=dataset.source_url,
          )

          # Save individual chunk
          chunk_path = chunks_out / f"{chunk_id}.json"
          chunk_path.write_text(
            chunk.model_dump_json(indent=2), encoding="utf-8"
          )

          # Stream write to jsonl
          f_jsonl.write(chunk.model_dump_json() + "\n")
          chunks_count += 1

      except Exception as exc:
        failures.append(
          ParsingFailure(
            url=dataset.source_url,
            local_path=local_path_str,
            reason=f"failed to parse/chunk dataset page: {exc}",
          )
        )

    # 2. Parse Documents (can be HTML or PDF)
    for doc in documents:
      document_id_error = _safe_output_id_error("document_id", doc.document_id)
      if document_id_error:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=doc.local_path,
            reason=document_id_error,
          )
        )
        continue

      dataset_id_error = _safe_output_id_error("dataset_id", doc.dataset_id)
      if dataset_id_error:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=doc.local_path,
            reason=dataset_id_error,
          )
        )
        continue

      # Stop/fail if a document cannot be mapped to any dataset ID
      if doc.dataset_id not in valid_dataset_ids:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=doc.local_path,
            reason=f"document dataset_id '{doc.dataset_id}' not found in datasets metadata",
          )
        )
        continue

      local_path_str = doc.local_path.strip()
      if not local_path_str:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path="",
            reason="document has empty local path",
          )
        )
        continue

      local_path = Path(local_path_str)
      if not local_path.is_file():
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=local_path_str,
            reason="document file does not exist locally",
          )
        )
        continue

      # Enforce explicit supported document kind check
      if doc.document_kind not in {"pdf", "html", "xlsx"}:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=local_path_str,
            reason=f"unsupported document kind: {doc.document_kind}",
          )
        )
        continue

      try:
        if doc.document_kind == "pdf":
          pages = parse_pdf(local_path)
          
          # Check if the extracted PDF text is completely empty (OCR stop condition)
          combined_text = "\n\n".join(page_text for _, page_text in pages).strip()
          if not combined_text:
            failures.append(
              ParsingFailure(
                url=doc.source_url,
                local_path=local_path_str,
                reason="extracted PDF text is empty (PDF may contain only scanned images and require OCR)",
              )
            )
            continue

          # Save combined clean text
          txt_path = pdf_out / f"{doc.document_id}.txt"
          txt_path.write_text(combined_text, encoding="utf-8")
          parsed_documents_count += 1

          # Chunk text page-by-page
          for page_num, page_text in pages:
            if not page_text.strip():
              continue
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

              # Save individual chunk
              chunk_path = chunks_out / f"{chunk_id}.json"
              chunk_path.write_text(
                chunk.model_dump_json(indent=2), encoding="utf-8"
              )

              # Stream write to jsonl
              f_jsonl.write(chunk.model_dump_json() + "\n")
              chunks_count += 1

        elif doc.document_kind == "html":
          text = parse_html(local_path)
          if not text or not text.strip():
            failures.append(
              ParsingFailure(
                url=doc.source_url,
                local_path=local_path_str,
                reason="extracted HTML text is empty",
              )
            )
            continue

          # Save clean raw text
          txt_path = html_out / f"{doc.document_id}.txt"
          txt_path.write_text(text, encoding="utf-8")
          parsed_documents_count += 1

          # Chunk text (page = None for HTML)
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
              page=None,
              text=chunk_txt,
              dataset=doc.dataset_id,
              url=doc.source_url,
            )

            # Save individual chunk
            chunk_path = chunks_out / f"{chunk_id}.json"
            chunk_path.write_text(
              chunk.model_dump_json(indent=2), encoding="utf-8"
            )

            # Stream write to jsonl
            f_jsonl.write(chunk.model_dump_json() + "\n")
            chunks_count += 1

        elif doc.document_kind == "xlsx":
          sheets = parse_xlsx(local_path)
          combined_text = "\n\n".join(
            sheet_text for _, sheet_text in sheets
          ).strip()
          if not combined_text:
            failures.append(
              ParsingFailure(
                url=doc.source_url,
                local_path=local_path_str,
                reason="extracted XLSX text is empty",
              )
            )
            continue

          txt_path = xlsx_out / f"{doc.document_id}.txt"
          txt_path.write_text(combined_text, encoding="utf-8")
          parsed_documents_count += 1

          for sheet_num, sheet_text in sheets:
            if not sheet_text.strip():
              continue
            sheet_chunks = chunk_text(
              sheet_text,
              chunk_size=config.chunk_size,
              chunk_overlap=config.chunk_overlap,
            )
            for idx, chunk_txt in enumerate(sheet_chunks):
              chunk_id = f"{doc.document_id}__s{sheet_num}__chunk_{idx}"
              chunk = ChunkMetadata(
                chunk_id=chunk_id,
                source_document=doc.local_path,
                page=sheet_num,
                text=chunk_txt,
                dataset=doc.dataset_id,
                url=doc.source_url,
              )

              chunk_path = chunks_out / f"{chunk_id}.json"
              chunk_path.write_text(
                chunk.model_dump_json(indent=2), encoding="utf-8"
              )

              f_jsonl.write(chunk.model_dump_json() + "\n")
              chunks_count += 1

      except Exception as exc:
        failures.append(
          ParsingFailure(
            url=doc.source_url,
            local_path=local_path_str,
            reason=f"failed to parse/chunk document: {exc}",
          )
        )

  result = ParsingResult(
    config=config,
    parsed_datasets_count=parsed_datasets_count,
    parsed_documents_count=parsed_documents_count,
    chunks_count=chunks_count,
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
  "parse_xlsx",
  "run_parsing",
]
