"""Read-only lexical retrieval over CMS KB metadata and parsed chunks."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .parsing import ChunkMetadata


RecordType = Literal["dataset", "document", "variable", "chunk"]

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


class RetrievalConfig(BaseModel):
  datasets_metadata_path: Path = Path("data/metadata/datasets.csv")
  documents_metadata_path: Path = Path("data/metadata/documents.csv")
  variables_metadata_path: Path = Path("data/metadata/variables.csv")
  chunks_jsonl_path: Path = Path("data/parsed/chunks.jsonl")


class RetrievableRecord(BaseModel):
  record_id: str
  record_type: RecordType
  title: str
  dataset_id: str = ""
  text: str
  source_url: str
  source_document: str = ""
  page: int | None = None
  exact_terms: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
  record_id: str
  record_type: RecordType
  title: str
  dataset_id: str
  score: float
  snippet: str
  source_url: str
  source_document: str = ""
  page: int | None = None


def _tokens(value: str) -> list[str]:
  return TOKEN_PATTERN.findall(value.lower())


def _required_headers(reader: csv.DictReader[str], path: Path, headers: list[str]) -> None:
  if reader.fieldnames is None:
    raise ValueError(f"CSV has no header: {path}")
  missing = [header for header in headers if header not in reader.fieldnames]
  if missing:
    raise ValueError(f"{path} is missing columns: {', '.join(missing)}")


def _read_csv_rows(path: Path, required_headers: list[str]) -> list[dict[str, str]]:
  with path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    _required_headers(reader, path, required_headers)
    return [dict(row) for row in reader]


def _required_value(raw_row: dict[str, str], field: str, row_id: str) -> str:
  value = raw_row.get(field, "").strip()
  if not value:
    raise ValueError(f"{row_id} has empty required field: {field}")
  return value


def _dataset_record(raw_row: dict[str, str]) -> RetrievableRecord:
  dataset_id = _required_value(raw_row, "dataset_id", "dataset row")
  title = raw_row.get("name", "") or dataset_id
  text = " ".join(
    value
    for value in [
      dataset_id,
      title,
      raw_row.get("program", ""),
      raw_row.get("category", ""),
      raw_row.get("availability", ""),
      raw_row.get("extraction_notes", ""),
    ]
    if value
  )
  return RetrievableRecord(
    record_id=dataset_id,
    record_type="dataset",
    title=title,
    dataset_id=dataset_id,
    text=text,
    source_url=_required_value(raw_row, "source_url", dataset_id),
    source_document=raw_row.get("local_path", ""),
    exact_terms=[dataset_id, title],
  )


def _document_record(raw_row: dict[str, str]) -> RetrievableRecord:
  document_id = _required_value(raw_row, "document_id", "document row")
  title = raw_row.get("title", "") or document_id
  dataset_id = raw_row.get("dataset_id", "")
  text = " ".join(
    value
    for value in [
      document_id,
      dataset_id,
      title,
      raw_row.get("document_kind", ""),
      raw_row.get("content_type", ""),
      raw_row.get("extraction_notes", ""),
    ]
    if value
  )
  return RetrievableRecord(
    record_id=document_id,
    record_type="document",
    title=title,
    dataset_id=dataset_id,
    text=text,
    source_url=_required_value(raw_row, "source_url", document_id),
    source_document=raw_row.get("local_path", ""),
    exact_terms=[document_id, dataset_id, title],
  )


def _variable_record(raw_row: dict[str, str]) -> RetrievableRecord:
  variable_id = _required_value(raw_row, "variable_id", "variable row")
  variable_name = _required_value(raw_row, "variable_name", variable_id)
  dataset_id = raw_row.get("dataset_id", "")
  page_value = raw_row.get("page", "").strip()
  text = " ".join(
    value
    for value in [
      variable_id,
      variable_name,
      dataset_id,
      raw_row.get("definition", ""),
      raw_row.get("aliases", "").replace("|", " "),
      raw_row.get("years", "").replace("|", " "),
      raw_row.get("extraction_notes", ""),
    ]
    if value
  )
  return RetrievableRecord(
    record_id=variable_id,
    record_type="variable",
    title=variable_name,
    dataset_id=dataset_id,
    text=text,
    source_url=_required_value(raw_row, "source_url", variable_id),
    source_document=raw_row.get("source_document", ""),
    page=int(page_value) if page_value else None,
    exact_terms=[variable_id, variable_name, dataset_id],
  )


def _chunk_record(chunk: ChunkMetadata) -> RetrievableRecord:
  if not chunk.url.strip():
    raise ValueError(f"{chunk.chunk_id} has empty required field: url")
  return RetrievableRecord(
    record_id=chunk.chunk_id,
    record_type="chunk",
    title=chunk.chunk_id,
    dataset_id=chunk.dataset,
    text=chunk.text,
    source_url=chunk.url,
    source_document=chunk.source_document,
    page=chunk.page,
    exact_terms=[chunk.chunk_id, chunk.dataset],
  )


def _load_chunks(path: Path) -> list[RetrievableRecord]:
  records: list[RetrievableRecord] = []
  with path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
      if not line.strip():
        continue
      try:
        chunk = ChunkMetadata.model_validate(json.loads(line))
      except Exception as exc:
        raise ValueError(f"failed to parse chunk JSON on line {line_number}: {exc}") from exc
      records.append(_chunk_record(chunk))
  return records


def load_retrievable_records(config: RetrievalConfig) -> list[RetrievableRecord]:
  records: list[RetrievableRecord] = []

  dataset_rows = _read_csv_rows(
    config.datasets_metadata_path,
    ["dataset_id", "name", "source_url"],
  )
  document_rows = _read_csv_rows(
    config.documents_metadata_path,
    ["document_id", "dataset_id", "title", "source_url"],
  )

  records.extend(_dataset_record(row) for row in dataset_rows)
  records.extend(_document_record(row) for row in document_rows)

  if config.variables_metadata_path.is_file():
    variable_rows = _read_csv_rows(
      config.variables_metadata_path,
      [
        "variable_id",
        "variable_name",
        "dataset_id",
        "definition",
        "source_url",
        "source_document",
        "page",
      ],
    )
    records.extend(_variable_record(row) for row in variable_rows)

  if config.chunks_jsonl_path.is_file():
    records.extend(_load_chunks(config.chunks_jsonl_path))

  return records


def _idf_by_token(records: list[RetrievableRecord]) -> dict[str, float]:
  document_count = len(records)
  document_frequencies: Counter[str] = Counter()
  for record in records:
    document_frequencies.update(set(_tokens(record.text)))
  return {
    token: math.log(1 + ((document_count - frequency + 0.5) / (frequency + 0.5)))
    for token, frequency in document_frequencies.items()
  }


def _field_boost(query: str, query_tokens: list[str], record: RetrievableRecord) -> float:
  boost = 0.0
  exact_values = [value.lower() for value in record.exact_terms if value]
  if query in exact_values:
    boost += 8.0
  for token in query_tokens:
    if token in exact_values:
      boost += 4.0
  if query and query in record.text.lower():
    boost += 2.0
  return boost


def _record_score(
  query: str,
  query_tokens: list[str],
  record: RetrievableRecord,
  idf: dict[str, float],
  average_length: float,
) -> float:
  record_tokens = _tokens(record.text)
  if not record_tokens:
    return 0.0

  counts = Counter(record_tokens)
  score = 0.0
  k1 = 1.2
  b = 0.75
  length_norm = 1 - b + b * (len(record_tokens) / average_length)

  for token in query_tokens:
    frequency = counts[token]
    if frequency == 0:
      continue
    numerator = frequency * (k1 + 1)
    denominator = frequency + (k1 * length_norm)
    score += idf.get(token, 0.0) * (numerator / denominator)

  return score + _field_boost(query, query_tokens, record)


def _snippet(text: str, query_tokens: list[str], max_length: int = 180) -> str:
  cleaned = re.sub(r"\s+", " ", text).strip()
  if len(cleaned) <= max_length:
    return cleaned

  lowered = cleaned.lower()
  first_match = min(
    (lowered.find(token) for token in query_tokens if lowered.find(token) != -1),
    default=0,
  )
  start = max(0, first_match - 40)
  end = min(len(cleaned), start + max_length)
  snippet = cleaned[start:end].strip()
  if start > 0:
    snippet = f"...{snippet}"
  if end < len(cleaned):
    snippet = f"{snippet}..."
  return snippet


def search_records(
  query: str,
  records: list[RetrievableRecord],
  limit: int = 10,
) -> list[SearchResult]:
  normalized_query = query.strip().lower()
  if not normalized_query:
    raise ValueError("query must not be empty")
  if limit <= 0:
    raise ValueError("limit must be greater than 0")

  query_tokens = _tokens(normalized_query)
  if not query_tokens:
    raise ValueError("query must contain at least one searchable token")
  if not records:
    return []

  idf = _idf_by_token(records)
  token_lengths = [len(_tokens(record.text)) for record in records]
  if sum(token_lengths) == 0:
    return []
  average_length = sum(token_lengths) / len(token_lengths)
  scored_records = [
    (
      _record_score(normalized_query, query_tokens, record, idf, average_length),
      record,
    )
    for record in records
  ]

  results = [
    SearchResult(
      record_id=record.record_id,
      record_type=record.record_type,
      title=record.title,
      dataset_id=record.dataset_id,
      score=round(score, 6),
      snippet=_snippet(record.text, query_tokens),
      source_url=record.source_url,
      source_document=record.source_document,
      page=record.page,
    )
    for score, record in scored_records
    if score > 0
  ]
  return sorted(
    results,
    key=lambda result: (-result.score, result.record_type, result.record_id),
  )[:limit]


def run_retrieval(
  config: RetrievalConfig,
  query: str,
  limit: int = 10,
) -> list[SearchResult]:
  records = load_retrievable_records(config)
  return search_records(query, records, limit)


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Search CMS KB metadata and parsed chunks with local lexical retrieval."
  )
  parser.add_argument("--query", required=True)
  parser.add_argument("--limit", type=int, default=10)
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
    "--chunks-jsonl",
    type=Path,
    default=Path("data/parsed/chunks.jsonl"),
  )
  parser.add_argument("--json", action="store_true")
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
  )

  try:
    results = run_retrieval(config, args.query, args.limit)
  except Exception as exc:
    print(f"Error executing retrieval: {exc}", file=sys.stderr)
    return 1

  if args.json:
    print(json.dumps([result.model_dump() for result in results], indent=2))
    return 0

  for result in results:
    page = f" page {result.page}" if result.page is not None else ""
    print(
      f"{result.score:.3f}\t{result.record_type}\t{result.record_id}\t"
      f"{result.source_url}{page}\n{result.snippet}"
    )
  return 0


__all__ = [
  "RetrievableRecord",
  "RetrievalConfig",
  "SearchResult",
  "build_arg_parser",
  "load_retrievable_records",
  "main",
  "run_retrieval",
  "search_records",
]
