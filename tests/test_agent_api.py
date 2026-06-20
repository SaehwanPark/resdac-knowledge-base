from __future__ import annotations

import csv
import json
from pathlib import Path

from cms_kb.agent_api import (
  AgentContextConfig,
  build_agent_context,
  context_hit_from_search_result,
  main,
)
from cms_kb.parsing import ChunkMetadata
from cms_kb.retrieval import RetrievalConfig, SearchResult, build_index


VARIABLE_URL = "https://resdac.org/cms-data/variables/encrypted-ccw-beneficiary-id"


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
    variable_source = tmp_path / "raw" / "mbsf-data.html"
    variable_source.parent.mkdir(parents=True, exist_ok=True)
    variable_source.write_text(
      """
      <html><body><table><tr>
        <td>BENE_ID</td>
        <td><a href="/cms-data/variables/encrypted-ccw-beneficiary-id">Encrypted CCW Beneficiary ID</a></td>
      </tr></table></body></html>
      """,
      encoding="utf-8",
    )
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
        str(variable_source),
        "https://resdac.org/cms-data/files/mbsf/data-documentation",
        "",
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


def _write_archive_manifest_fixture(tmp_path: Path) -> Path:
  variable_page = tmp_path / "data" / "raw" / "html" / "variable_page" / "bene.html"
  variable_page.parent.mkdir(parents=True, exist_ok=True)
  variable_page.write_text(
    "<html><body>Encrypted CCW Beneficiary ID</body></html>",
    encoding="utf-8",
  )
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  with manifest_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow([
      "url",
      "resource_kind",
      "asset_kind",
      "source_url",
      "source_title",
      "content_type",
      "http_status",
      "archive_state",
      "downloaded_at_utc",
      "sha256",
      "local_path",
      "error",
    ])
    writer.writerow([
      VARIABLE_URL,
      "variable_page",
      "",
      "https://resdac.org/cms-data/files/mbsf/data-documentation",
      "MBSF Data Documentation",
      "text/html",
      "200",
      "archived",
      "2026-06-16T00:00:00Z",
      "fake-sha",
      str(variable_page),
      "",
    ])
  return manifest_path


def test_build_agent_context_returns_ordered_cited_hits(tmp_path: Path) -> None:
  config = AgentContextConfig(
    retrieval=_write_metadata_fixture(tmp_path),
    archive_manifest_path=tmp_path / "missing_archive_manifest.csv",
    default_limit=5,
  )

  response = build_agent_context(config, "BENE_ID")

  assert response.query == "BENE_ID"
  assert response.results[0].record_id == "mbsf__var__bene-id"
  assert response.results[0].record_type == "variable"
  assert response.results[0].citation.source_url == (
    "https://resdac.org/cms-data/files/mbsf/data-documentation"
  )
  assert response.results[0].citation.page is None
  assert response.results[0].citation.variable_url == (
    VARIABLE_URL
  )
  assert response.results[0].citation.variable_document == ""


def test_build_agent_context_populates_archived_variable_document(
  tmp_path: Path,
) -> None:
  manifest_path = _write_archive_manifest_fixture(tmp_path)
  config = AgentContextConfig(
    retrieval=_write_metadata_fixture(tmp_path),
    archive_manifest_path=manifest_path,
    default_limit=5,
  )

  response = build_agent_context(config, "BENE_ID")

  assert response.results[0].citation.variable_url == VARIABLE_URL
  assert response.results[0].citation.variable_document.endswith(
    "data/raw/html/variable_page/bene.html"
  )


def test_build_agent_context_uses_explicit_limit(tmp_path: Path) -> None:
  config = AgentContextConfig(retrieval=_write_metadata_fixture(tmp_path), default_limit=5)

  response = build_agent_context(config, "mbsf", limit=1)

  assert len(response.results) == 1


def test_context_hit_populates_local_standalone_variable_document(tmp_path: Path) -> None:
  variable_page = tmp_path / "raw" / "encrypted-ccw-beneficiary-id.html"
  variable_page.parent.mkdir(parents=True, exist_ok=True)
  variable_page.write_text("<html><body>Encrypted CCW Beneficiary ID</body></html>", encoding="utf-8")
  result = SearchResult(
    record_id="mbsf__var__bene-id",
    record_type="variable",
    title="BENE_ID",
    dataset_id="mbsf",
    score=1.0,
    snippet="BENE_ID Encrypted CCW Beneficiary ID",
    source_url="https://resdac.org/cms-data/variables/encrypted-ccw-beneficiary-id",
    source_document=str(variable_page),
    page=None,
  )

  hit = context_hit_from_search_result(result)

  assert hit.citation.variable_url == (
    VARIABLE_URL
  )
  assert hit.citation.variable_document == str(variable_page)


def test_agent_context_cli_outputs_json_with_nested_citations(
  tmp_path: Path, capsys
) -> None:
  retrieval_config = _write_metadata_fixture(tmp_path)
  manifest_path = _write_archive_manifest_fixture(tmp_path)

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
    "--archive-manifest",
    str(manifest_path),
    "--database-path",
    str(retrieval_config.database_path),
    "--json",
  ])

  captured = capsys.readouterr()
  payload = json.loads(captured.out)
  assert exit_code == 0
  assert payload["query"] == "BENE_ID"
  assert payload["results"][0]["record_id"] == "mbsf__var__bene-id"
  assert payload["results"][0]["citation"]["source_url"]
  assert payload["results"][0]["citation"]["variable_url"] == (
    VARIABLE_URL
  )
  assert payload["results"][0]["citation"]["variable_document"].endswith(
    "data/raw/html/variable_page/bene.html"
  )


def test_agent_context_cli_failure_for_empty_query(tmp_path: Path, capsys) -> None:
  retrieval_config = _write_metadata_fixture(tmp_path)

  exit_code = main([
    "--query",
    " ",
    "--datasets-metadata",
    str(retrieval_config.datasets_metadata_path),
    "--documents-metadata",
    str(retrieval_config.documents_metadata_path),
    "--database-path",
    str(retrieval_config.database_path),
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
    "--database-path",
    str(retrieval_config.database_path),
  ])

  captured = capsys.readouterr()
  assert exit_code == 1
  assert "Error building agent context" in captured.err
