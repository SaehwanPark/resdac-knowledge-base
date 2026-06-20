from __future__ import annotations

import csv
import json
from pathlib import Path

from cms_kb.parsing import ChunkMetadata
from cms_kb.retrieval import (
  RetrievableRecord,
  RetrievalConfig,
  build_index,
  load_retrievable_records,
  main,
  main_index,
  run_retrieval,
  search_records,
)


def _write_metadata_fixture(tmp_path: Path, include_variables: bool = True) -> RetrievalConfig:
  metadata_dir = tmp_path / "data" / "metadata"
  parsed_dir = tmp_path / "data" / "parsed"
  metadata_dir.mkdir(parents=True, exist_ok=True)
  parsed_dir.mkdir(parents=True, exist_ok=True)

  datasets_csv = metadata_dir / "datasets.csv"
  with datasets_csv.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
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
      "mbsf",
      "Medicare Beneficiary Summary File",
      "Medicare",
      "Enrollment",
      "Available",
      "https://resdac.org/cms-data/files/mbsf",
      str(tmp_path / "raw" / "mbsf.html"),
      "fake-sha",
      "",
    ])

  documents_csv = metadata_dir / "documents.csv"
  with documents_csv.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
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
      "mbsf__codebook",
      "mbsf",
      "MBSF Codebook",
      "pdf",
      "https://resdac.org/cms-data/files/mbsf-codebook",
      str(tmp_path / "raw" / "mbsf-codebook.pdf"),
      "fake-doc-sha",
      "application/pdf",
      "",
    ])

  variables_csv = metadata_dir / "variables.csv"
  if include_variables:
    with variables_csv.open("w", newline="", encoding="utf-8") as handle:
      writer = csv.writer(handle)
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
        "mbsf__var__bene-id",
        "BENE_ID",
        "mbsf",
        "Beneficiary identifier used to link claims and enrollment records.",
        "beneficiary id",
        "2020",
        str(tmp_path / "parsed" / "mbsf.txt"),
        "https://resdac.org/cms-data/files/mbsf-codebook",
        "3",
        "chunk-1",
        "",
      ])

  chunks_jsonl = parsed_dir / "chunks.jsonl"
  chunks = [
    ChunkMetadata(
      chunk_id="chunk-1",
      source_document=str(tmp_path / "parsed" / "mbsf.txt"),
      page=3,
      text="Dual eligibility indicators describe Medicare and Medicaid enrollment.",
      dataset="mbsf",
      url="https://resdac.org/cms-data/files/mbsf-codebook",
    )
  ]
  chunks_jsonl.write_text(
    "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
    encoding="utf-8",
  )

  config = RetrievalConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    variables_metadata_path=variables_csv,
    chunks_jsonl_path=chunks_jsonl,
    database_path=tmp_path / "data" / "index" / "retrieval.sqlite",
  )
  build_index(config)
  return config


def test_load_retrievable_records_uses_optional_inputs(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)

  records = load_retrievable_records(config)

  assert [record.record_type for record in records] == [
    "dataset",
    "document",
    "variable",
    "chunk",
  ]
  assert all(record.source_url for record in records)


def test_load_retrievable_records_allows_missing_optional_inputs(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path, include_variables=False)
  config.chunks_jsonl_path.unlink()

  records = load_retrievable_records(config)

  assert [record.record_type for record in records] == ["dataset", "document"]


def test_build_index_creates_tables_and_inserts_records(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  config.database_path = tmp_path / "data" / "index" / "retrieval.sqlite"

  build_index(config)

  assert config.database_path.is_file()

  import sqlite3
  conn = sqlite3.connect(config.database_path)
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert "records" in tables
    assert "records_fts" in tables

    cursor.execute("SELECT COUNT(*) FROM records;")
    records_count = cursor.fetchone()[0]
    assert records_count == 4

    cursor.execute("SELECT COUNT(*) FROM records_fts;")
    fts_count = cursor.fetchone()[0]
    assert fts_count == 4

    cursor.execute("SELECT record_id, record_type, title, exact_terms FROM records ORDER BY record_id;")
    rows = cursor.fetchall()
    assert rows[0][0] == "chunk-1"
    assert rows[0][1] == "chunk"
    assert rows[0][2] == "chunk-1"

    assert rows[1][0] == "mbsf"
    assert rows[1][1] == "dataset"
    assert json.loads(rows[1][3]) == ["mbsf", "Medicare Beneficiary Summary File"]
  finally:
    conn.close()


def test_exact_variable_match_ranks_above_generic_chunk(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)

  results = run_retrieval(config, "BENE_ID", limit=5)

  assert results[0].record_type == "variable"
  assert results[0].record_id == "mbsf__var__bene-id"
  assert results[0].source_url == "https://resdac.org/cms-data/files/mbsf-codebook"
  assert results[0].page == 3


def test_text_query_matches_chunk_with_citation(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)

  results = run_retrieval(config, "dual eligibility", limit=5)

  assert results[0].record_type == "chunk"
  assert "Dual eligibility" in results[0].snippet
  assert results[0].source_url == "https://resdac.org/cms-data/files/mbsf-codebook"


def test_search_records_rejects_empty_query(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  records = load_retrievable_records(config)

  try:
    search_records("   ", records)
  except ValueError as exc:
    assert "query must not be empty" in str(exc)
  else:
    raise AssertionError("empty query should fail")


def test_search_records_returns_empty_when_records_have_no_searchable_tokens() -> None:
  records = [
    RetrievableRecord(
      record_id="punctuation",
      record_type="chunk",
      title="Punctuation",
      text="!!!",
      dataset_id="ds",
      source_url="https://example.com/source",
      source_document="source.txt",
      page=None,
    )
  ]

  assert search_records("BENE_ID", records) == []


def test_retrieval_cli_json_output(tmp_path: Path, capsys) -> None:
  config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    "BENE_ID",
    "--limit",
    "5",
    "--datasets-metadata",
    str(config.datasets_metadata_path),
    "--documents-metadata",
    str(config.documents_metadata_path),
    "--variables-metadata",
    str(config.variables_metadata_path),
    "--chunks-jsonl",
    str(config.chunks_jsonl_path),
    "--database-path",
    str(config.database_path),
    "--json",
  ])

  captured = capsys.readouterr()
  payload = json.loads(captured.out)
  assert exit_code == 0
  assert payload[0]["record_id"] == "mbsf__var__bene-id"
  assert payload[0]["source_url"]


def test_retrieval_cli_failure_for_missing_required_input(
  tmp_path: Path, capsys
) -> None:
  config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    "BENE_ID",
    "--datasets-metadata",
    str(tmp_path / "missing.csv"),
    "--documents-metadata",
    str(config.documents_metadata_path),
    "--variables-metadata",
    str(config.variables_metadata_path),
    "--chunks-jsonl",
    str(config.chunks_jsonl_path),
    "--database-path",
    str(config.database_path),
  ])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "Error executing retrieval" in captured.err


def test_load_retrievable_records_rejects_blank_citation(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  rows = config.datasets_metadata_path.read_text(encoding="utf-8").splitlines()
  rows[1] = rows[1].replace("https://resdac.org/cms-data/files/mbsf", "")
  config.datasets_metadata_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

  try:
    load_retrievable_records(config)
  except ValueError as exc:
    assert "empty required field: source_url" in str(exc)
  else:
    raise AssertionError("blank source_url should fail")


def test_retrieval_cli_failure_for_empty_query(tmp_path: Path, capsys) -> None:
  config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    " ",
    "--datasets-metadata",
    str(config.datasets_metadata_path),
    "--documents-metadata",
    str(config.documents_metadata_path),
    "--database-path",
    str(config.database_path),
  ])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "query must not be empty" in captured.err


def test_main_index_cli(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  db_path = tmp_path / "data" / "index" / "cli_built.sqlite"

  exit_code = main_index([
    "--datasets-metadata",
    str(config.datasets_metadata_path),
    "--documents-metadata",
    str(config.documents_metadata_path),
    "--variables-metadata",
    str(config.variables_metadata_path),
    "--chunks-jsonl",
    str(config.chunks_jsonl_path),
    "--database-path",
    str(db_path),
  ])

  assert exit_code == 0
  assert db_path.is_file()
