"""Read-only lexical retrieval over CMS KB metadata and parsed chunks.

This module houses the core search engine of the CMS Knowledge Base. It uses a custom
BM25 (Best Matching 25) TF-IDF ranking implementation enhanced with exact-term field
boosting.

Architecture & Data Flow:
- Multiple heterogeneous source schemas (datasets, documents, variables, text chunks)
  are parsed and normalized into a unified schema represented by `RetrievableRecord`.
- On query execution, the search engine computes term frequency relative to the average
  document length and token inverse document frequency (IDF) using a BM25 variant.
- Custom exact matches on identifier fields (such as `variable_id` or `dataset_id`) are
  highly boosted to ensure precise direct query resolution.
- Finally, search results are formatted into snippets centering on matched tokens
  and returned as a sorted list of `SearchResult` objects.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .parsing import ChunkMetadata


RecordType = Literal["dataset", "document", "variable", "chunk"]

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


class RetrievalConfig(BaseModel):
  """Configuration holding file paths for the knowledge base catalogs and chunks."""
  datasets_metadata_path: Path = Path("data/metadata/datasets.csv")
  documents_metadata_path: Path = Path("data/metadata/documents.csv")
  variables_metadata_path: Path = Path("data/metadata/variables.csv")
  chunks_jsonl_path: Path = Path("data/parsed/chunks.jsonl")
  database_path: Path = Path("data/index/retrieval.sqlite")

  hybrid_search_enabled: bool = False
  semantic_model_name: str = "all-MiniLM-L6-v2"
  semantic_weight: float = 0.5



class RetrievableRecord(BaseModel):
  """A search index record representing a flattened entity in the CMS KB.

  All parsed items (datasets, files, variables, chunks) are mapped to this format
  for indexation and lexical analysis.

  Attributes:
    record_id: Unique identifier of the entity.
    record_type: Kind of record ('dataset', 'document', 'variable', 'chunk').
    title: Human-readable name/label.
    dataset_id: The ID of the parent or associated dataset.
    text: Normalized content text block scanned by the search query.
    source_url: Original source citation web URL.
    source_document: Local path to the raw archived document.
    page: Optional page number if the source document is a PDF.
    exact_terms: High-priority strings (like codes, acronyms) that qualify for exact field boosting.
  """
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
  """A scored and matched retrieval hit returned by the search engine.

  Attributes:
    record_id: Identifier of the matched entity.
    record_type: Type of the entity.
    title: Human-readable name.
    dataset_id: Parent dataset identifier.
    score: The lexical score calculated by BM25 plus exact-match boosts.
    snippet: The text excerpt containing highlighted search query terms.
    source_url: Original citation URL.
    source_document: Local path to the archived source document.
    page: Optional page number of the source document.
  """
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
  """Calculates the BM25-variant Inverse Document Frequency (IDF) for all unique tokens.

  This downweights tokens that occur frequently across the entire corpus
  (such as common words like 'the' or 'data') and boosts rare tokens.
  """
  document_count = len(records)
  document_frequencies: Counter[str] = Counter()
  for record in records:
    document_frequencies.update(set(_tokens(record.text)))
  return {
    token: math.log(1 + ((document_count - frequency + 0.5) / (frequency + 0.5)))
    for token, frequency in document_frequencies.items()
  }


def _field_boost(query: str, query_tokens: list[str], record: RetrievableRecord) -> float:
  """Calculates field boosting values based on exact matches of key identifiers.

  For example, if the query matches a variable ID (e.g. 'BENE_ID') exactly,
  it gets a significant boost to ensure it ranks ahead of general text matches.
  """
  boost = 0.0
  exact_values = [value.lower() for value in record.exact_terms if value]
  if query in exact_values:
    # Large boost for exact query match on key identifiers
    boost += 8.0
  for token in set(query_tokens):
    if token in exact_values:
      # Modest boost for query sub-tokens matching identifiers
      boost += 4.0
  if query and query in record.text.lower():
    # Small boost for substring inclusion
    boost += 2.0
  return boost


def _record_score(
  query: str,
  query_tokens: list[str],
  record: RetrievableRecord,
  idf: dict[str, float],
  average_length: float,
) -> float:
  """Computes the final retrieval score for a record using BM25 and exact field boosts.

  Uses standard k1 and b tuning parameters to normalize document length.
  """
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
  """Generates a contextual text excerpt showing query term matches.

  Finds the first occurrence of any search token in the text and slices a window
  of up to `max_length` characters around it, appending ellipses if truncated.
  """
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
  """Searches across an in-memory list of retrievable records.

  Computes BM25 scores and exact boosts on-the-fly, sorts by score, and returns
  the top search results up to the limit.

  Args:
    query: The query text containing one or more terms.
    records: Pre-loaded RetrievableRecords to search over.
    limit: The maximum number of search results to return.

  Returns:
    A list of SearchResult objects sorted descending by score.
  """
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




_MODEL_CACHE: dict[str, Any] = {}


def _get_embedding_model(model_name: str) -> Any:
  if model_name not in _MODEL_CACHE:
    try:
      from sentence_transformers import SentenceTransformer
    except ImportError as exc:
      raise ImportError(
        "sentence-transformers is required for semantic search. "
        "Please run 'uv sync --extra semantic' to install it."
      ) from exc
    _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
  return _MODEL_CACHE[model_name]


def search_records_sqlite(
  query: str,
  db_path: Path,
  limit: int = 10,
  record_type: RecordType | None = None,
  hybrid: bool = False,
  semantic_weight: float = 0.5,
  model_name: str = "all-MiniLM-L6-v2",
) -> list[SearchResult]:
  """Searches across the SQLite FTS5 serving index.

  Calculates BM25 scores and exact boosts on candidates fetched from SQLite.
  Optionally combines with semantic cosine similarity using pre-computed embeddings.
  """
  try:
    import numpy as np
  except ImportError:
    np = None

  normalized_query = query.strip().lower()
  if not normalized_query:
    raise ValueError("query must not be empty")
  if limit <= 0:
    raise ValueError("limit must be greater than 0")

  # Clamp limit to prevent extreme memory use
  limit = min(limit, 1000)

  query_tokens = _tokens(normalized_query)
  if not query_tokens:
    raise ValueError("query must contain at least one searchable token")

  if not db_path.is_file():
    raise FileNotFoundError(f"Search index not found at {db_path}. Please run index building first.")

  # Escape search tokens by wrapping in double quotes
  match_expr = " OR ".join(f'"{t}"' for t in query_tokens)

  conn = sqlite3.connect(db_path)
  try:
    cursor = conn.cursor()
    # Check if record_embeddings table exists
    has_embeddings = False
    if hybrid:
      cursor.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='record_embeddings';"
      )
      if cursor.fetchone()[0] > 0:
        has_embeddings = True

    # Fetch a generous candidate pool to rerank in Python to apply exact boosts
    candidate_limit = max(500, limit * 5)
    if record_type:
      cursor.execute(
        """
        SELECT 
          r.record_id,
          r.record_type,
          r.title,
          r.dataset_id,
          r.source_url,
          r.source_document,
          r.page,
          r.exact_terms,
          fts.text,
          -bm25(records_fts, 10.0, 5.0, 2.0, 1.0) AS fts_score
        FROM records r
        JOIN records_fts fts ON r.record_id = fts.record_id
        WHERE records_fts MATCH ? AND r.record_type = ?
        ORDER BY fts_score DESC
        LIMIT ?
        """,
        (match_expr, record_type, candidate_limit),
      )
    else:
      cursor.execute(
        """
        SELECT 
          r.record_id,
          r.record_type,
          r.title,
          r.dataset_id,
          r.source_url,
          r.source_document,
          r.page,
          r.exact_terms,
          fts.text,
          -bm25(records_fts, 10.0, 5.0, 2.0, 1.0) AS fts_score
        FROM records r
        JOIN records_fts fts ON r.record_id = fts.record_id
        WHERE records_fts MATCH ?
        ORDER BY fts_score DESC
        LIMIT ?
        """,
        (match_expr, candidate_limit),
      )
    rows = cursor.fetchall()

    embeddings_map = {}
    if has_embeddings and rows:
      candidate_ids = [row[0] for row in rows]
      # Query in chunks to avoid SQLite's parameter limit (default 999 on older versions)
      chunk_size = 500
      for i in range(0, len(candidate_ids), chunk_size):
        chunk = candidate_ids[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(
          f"SELECT record_id, embedding FROM record_embeddings WHERE record_id IN ({placeholders})",
          chunk,
        )
        for rec_id, emb_blob in cursor.fetchall():
          embeddings_map[rec_id] = emb_blob
  finally:
    conn.close()

  # If hybrid search is enabled and table exists, initialize model and compute query embedding
  query_emb = None
  if has_embeddings and rows:
    try:
      if np is None:
        raise ImportError("numpy is not installed")
      model = _get_embedding_model(model_name)
      query_emb = model.encode(query, convert_to_numpy=True)
      query_norm = np.linalg.norm(query_emb)
      if query_norm > 0:
        query_emb = query_emb / query_norm

      # Validate dimension mismatch and non-empty mapping
      if not embeddings_map:
        has_embeddings = False
      else:
        assert np is not None
        first_emb_bytes = next(iter(embeddings_map.values()))
        first_emb = np.frombuffer(first_emb_bytes, dtype=np.float32)
        if len(first_emb) != len(query_emb):
          print(
            f"Warning: Embedding dimensions mismatch ({len(first_emb)} vs {len(query_emb)}). "
            "Falling back to lexical search.",
            file=sys.stderr,
          )
          has_embeddings = False
    except Exception as exc:
      print(f"Warning: Semantic search failed, falling back to lexical: {exc}", file=sys.stderr)
      has_embeddings = False

  # Normalize FTS5 scores across candidates if blending is active
  if has_embeddings and rows:
    fts_scores = [row[9] for row in rows]
    max_fts = max(fts_scores) if fts_scores else 0.0
    min_fts = min(fts_scores) if fts_scores else 0.0
    fts_range = max_fts - min_fts
  else:
    max_fts, min_fts, fts_range = 0.0, 0.0, 0.0

  results = []
  for (
    record_id,
    row_record_type,
    title,
    dataset_id,
    source_url,
    source_document,
    page,
    exact_terms_json,
    text,
    fts_score,
  ) in rows:
    exact_terms = json.loads(exact_terms_json)
    
    # Calculate cosine similarity if embeddings are present
    cosine_sim = 0.0
    if has_embeddings and query_emb is not None and record_id in embeddings_map:
      try:
        assert np is not None
        emb_bytes = embeddings_map[record_id]
        emb = np.frombuffer(emb_bytes, dtype=np.float32)
        emb_norm = np.linalg.norm(emb)
        if emb_norm > 0:
          emb = emb / emb_norm
          cosine_sim = float(np.dot(query_emb, emb))
      except Exception:
        pass

    # Blend scores
    if has_embeddings:
      norm_fts = (fts_score - min_fts) / fts_range if fts_range > 0.0 else 1.0
      blend_score = (1.0 - semantic_weight) * norm_fts + semantic_weight * cosine_sim
    else:
      blend_score = fts_score

    # Calculate exact-match boosts
    boost = 0.0
    exact_values = [val.lower() for val in exact_terms if val]
    if normalized_query in exact_values:
      boost += 8.0
    for token in set(query_tokens):
      if token in exact_values:
        boost += 4.0
    if normalized_query and normalized_query in text.lower():
      boost += 2.0
      
    final_score = blend_score + boost

    # Cast row_record_type to RecordType since SQLite returns TEXT
    res_type: RecordType = row_record_type # type: ignore

    results.append(
      SearchResult(
        record_id=record_id,
        record_type=res_type,
        title=title,
        dataset_id=dataset_id,
        score=round(final_score, 6),
        snippet=_snippet(text, query_tokens),
        source_url=source_url,
        source_document=source_document,
        page=page,
      )
    )

  return sorted(
    results,
    key=lambda result: (-result.score, result.record_type, result.record_id),
  )[:limit]


def run_retrieval(
  config: RetrievalConfig,
  query: str,
  limit: int = 10,
  record_type: RecordType | None = None,
) -> list[SearchResult]:
  """Performs the full SQLite-backed search pipeline for a query.

  Args:
    config: Configuration settings.
    query: The search input query.
    limit: Max results count.
    record_type: Optional record type filter.

  Returns:
    Sorted list of SearchResults.
  """
  if not config.datasets_metadata_path.is_file():
    raise FileNotFoundError(f"Datasets metadata file not found at {config.datasets_metadata_path}")
  if not config.documents_metadata_path.is_file():
    raise FileNotFoundError(f"Documents metadata file not found at {config.documents_metadata_path}")

  return search_records_sqlite(
    query,
    config.database_path,
    limit,
    record_type,
    hybrid=config.hybrid_search_enabled,
    semantic_weight=config.semantic_weight,
    model_name=config.semantic_model_name,
  )


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
  parser.add_argument(
    "--database-path",
    type=Path,
    default=Path("data/index/retrieval.sqlite"),
  )
  parser.add_argument("--legacy", action="store_true", help="Force the legacy in-memory search.")
  parser.add_argument("--json", action="store_true")
  parser.add_argument("--hybrid", action="store_true", help="Enable hybrid search (semantic reranking).")
  parser.add_argument("--semantic-weight", type=float, default=0.5, help="Semantic blend weight (0 to 1).")
  parser.add_argument("--semantic-model-name", type=str, default="all-MiniLM-L6-v2", help="SentenceTransformer model name.")
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
    database_path=args.database_path,
    hybrid_search_enabled=args.hybrid,
    semantic_weight=args.semantic_weight,
    semantic_model_name=args.semantic_model_name,
  )

  try:
    if args.legacy:
      records = load_retrievable_records(config)
      results = search_records(args.query, records, args.limit)
    else:
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


def build_index(config: RetrievalConfig, build_embeddings: bool = False) -> None:
  """Builds a SQLite FTS5 serving index from canonical metadata and chunks."""
  records = load_retrievable_records(config)
  db_dir = config.database_path.parent
  db_dir.mkdir(parents=True, exist_ok=True)
  temp_db_path = config.database_path.with_suffix(".sqlite.tmp")
  if temp_db_path.exists():
    temp_db_path.unlink()

  conn = sqlite3.connect(temp_db_path)
  success = False
  try:
    conn.execute("PRAGMA foreign_keys = ON;")
    # Create records table
    conn.execute("""
      CREATE TABLE records (
        record_id TEXT PRIMARY KEY,
        record_type TEXT NOT NULL,
        title TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_document TEXT NOT NULL,
        page INTEGER,
        exact_terms TEXT NOT NULL
      );
    """)
    # Create records_fts virtual table using FTS5 with unicode61 tokenizer preserving underscores
    conn.execute("""
      CREATE VIRTUAL TABLE records_fts USING fts5(
        record_id,
        title,
        dataset_id,
        text,
        tokenize="unicode61 tokenchars '_'"
      );
    """)

    if build_embeddings:
      conn.execute("""
        CREATE TABLE record_embeddings (
          record_id TEXT PRIMARY KEY,
          embedding BLOB NOT NULL
        );
      """)

    with conn:
      for r in records:
        conn.execute(
          "INSERT OR REPLACE INTO records (record_id, record_type, title, dataset_id, source_url, source_document, page, exact_terms) "
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
          (
            r.record_id,
            r.record_type,
            r.title,
            r.dataset_id,
            r.source_url,
            r.source_document,
            r.page,
            json.dumps(r.exact_terms),
          ),
        )
        conn.execute(
          "INSERT OR REPLACE INTO records_fts (record_id, title, dataset_id, text) VALUES (?, ?, ?, ?)",
          (
            r.record_id,
            r.title,
            r.dataset_id,
            r.text,
          ),
        )

      if build_embeddings:
        try:
          from sentence_transformers import SentenceTransformer
          import numpy as np
        except ImportError as exc:
          raise ImportError(
            "sentence-transformers and numpy are required for building embeddings. "
            "Please install them or run with semantic extras."
          ) from exc

        print(f"Loading embedding model '{config.semantic_model_name}'...")
        model = SentenceTransformer(config.semantic_model_name)
        texts = [r.text for r in records]
        print(f"Encoding {len(texts)} record embeddings...")
        embeddings = model.encode(texts, show_progress_bar=True, batch_size=128, normalize_embeddings=True)
        
        for r, emb in zip(records, embeddings):
          emb_arr = np.asarray(emb, dtype=np.float32)
          emb_bytes = emb_arr.tobytes()
          conn.execute(
            "INSERT OR REPLACE INTO record_embeddings (record_id, embedding) VALUES (?, ?)",
            (r.record_id, sqlite3.Binary(emb_bytes)),
          )
    success = True
  finally:
    conn.close()
    if not success and temp_db_path.exists():
      try:
        temp_db_path.unlink()
      except Exception as cleanup_exc:
        print(
          f"Warning: Failed to clean up temporary database {temp_db_path}: {cleanup_exc}",
          file=sys.stderr,
        )

  temp_db_path.replace(config.database_path)


def main_index(argv: list[str] | None = None) -> int:
  """CLI entry point to build search index."""
  parser = argparse.ArgumentParser(
    description="Build SQLite FTS5 search index from CMS KB metadata and parsed chunks."
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
    "--chunks-jsonl",
    type=Path,
    default=Path("data/parsed/chunks.jsonl"),
  )
  parser.add_argument(
    "--database-path",
    type=Path,
    default=Path("data/index/retrieval.sqlite"),
  )
  parser.add_argument(
    "--build-embeddings",
    action="store_true",
    help="Build semantic embeddings for hybrid search.",
  )
  parser.add_argument(
    "--semantic-model-name",
    type=str,
    default="all-MiniLM-L6-v2",
    help="Semantic model name to build embeddings with.",
  )
  args = parser.parse_args(argv)
  config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
    database_path=args.database_path,
    semantic_model_name=args.semantic_model_name,
  )

  try:
    print(f"Building search index at {config.database_path}...")
    build_index(config, build_embeddings=args.build_embeddings)
    print("Search index built successfully.")
    return 0
  except Exception as exc:
    print(f"Error building search index: {exc}", file=sys.stderr)
    return 1


__all__ = [
  "RetrievableRecord",
  "RetrievalConfig",
  "SearchResult",
  "build_arg_parser",
  "build_index",
  "load_retrievable_records",
  "main",
  "main_index",
  "run_retrieval",
  "search_records",
  "search_records_sqlite",
]

