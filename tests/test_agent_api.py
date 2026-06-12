from __future__ import annotations

import csv
import json
from pathlib import Path

from cms_kb.agent_api import AgentContextConfig, build_agent_context, main
from cms_kb.parsing import ChunkMetadata
from cms_kb.retrieval import RetrievalConfig


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

  return RetrievalConfig(
    datasets_metadata_path=datasets_csv,
    documents_metadata_path=documents_csv,
    variables_metadata_path=variables_csv,
    chunks_jsonl_path=chunks_jsonl,
  )


def test_build_agent_context_returns_ordered_cited_hits(tmp_path: Path) -> None:
  config = AgentContextConfig(retrieval=_write_metadata_fixture(tmp_path), default_limit=5)

  response = build_agent_context(config, "BENE_ID")

  assert response.query == "BENE_ID"
  assert response.results[0].record_id == "mbsf__var__bene-id"
  assert response.results[0].record_type == "variable"
  assert response.results[0].citation.source_url == (
    "https://resdac.org/cms-data/files/mbsf-codebook"
  )
  assert response.results[0].citation.page == 3


def test_build_agent_context_uses_explicit_limit(tmp_path: Path) -> None:
  config = AgentContextConfig(retrieval=_write_metadata_fixture(tmp_path), default_limit=5)

  response = build_agent_context(config, "mbsf", limit=1)

  assert len(response.results) == 1


def test_agent_context_cli_outputs_json_with_nested_citations(
  tmp_path: Path, capsys
) -> None:
  retrieval_config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    "BENE_ID",
    "--limit",
    "5",
    "--datasets-metadata",
    str(retrieval_config.datasets_metadata_path),
    "--documents-metadata",
    str(retrieval_config.documents_metadata_path),
    "--variables-metadata",
    str(retrieval_config.variables_metadata_path),
    "--chunks-jsonl",
    str(retrieval_config.chunks_jsonl_path),
    "--json",
  ])

  captured = capsys.readouterr()
  payload = json.loads(captured.out)
  assert exit_code == 0
  assert payload["query"] == "BENE_ID"
  assert payload["results"][0]["record_id"] == "mbsf__var__bene-id"
  assert payload["results"][0]["citation"]["source_url"]


def test_agent_context_cli_failure_for_empty_query(tmp_path: Path, capsys) -> None:
  retrieval_config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    " ",
    "--datasets-metadata",
    str(retrieval_config.datasets_metadata_path),
    "--documents-metadata",
    str(retrieval_config.documents_metadata_path),
  ])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "query must not be empty" in captured.err


def test_agent_context_cli_failure_for_missing_required_input(
  tmp_path: Path, capsys
) -> None:
  retrieval_config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    "BENE_ID",
    "--datasets-metadata",
    str(tmp_path / "missing.csv"),
    "--documents-metadata",
    str(retrieval_config.documents_metadata_path),
    "--variables-metadata",
    str(retrieval_config.variables_metadata_path),
    "--chunks-jsonl",
    str(retrieval_config.chunks_jsonl_path),
  ])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "Error building agent context" in captured.err
