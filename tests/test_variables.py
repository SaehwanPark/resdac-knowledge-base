from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from cms_kb.archive import ArchiveManifestRow, write_archive_manifest
from cms_kb.parsing import ChunkMetadata
from cms_kb.variables import (
  VariableExtractionConfig,
  VariableMetadataRow,
  _deduplicate_variables,
  extract_variables_from_chunk,
  main,
  read_chunks_jsonl,
  run_variable_extraction,
)


def _write_chunk_jsonl(path: Path, chunks: list[ChunkMetadata]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
    encoding="utf-8",
  )


def test_extract_variables_from_chunk_requires_definition_evidence() -> None:
  chunk = ChunkMetadata(
    chunk_id="chunk-1",
    source_document="/tmp/source.txt",
    page=3,
    text=(
      "BENE_ID: Beneficiary identifier, also known as beneficiary id, 2020.\n"
      "CLM_ID appears elsewhere without a definition."
    ),
    dataset="mbsf",
    url="https://resdac.org/cms-data/files/mbsf/data-documentation",
  )

  rows, skipped = extract_variables_from_chunk(chunk)

  assert skipped == 1
  assert len(rows) == 1
  assert rows[0].variable_id == "mbsf__var__bene-id"
  assert rows[0].variable_name == "BENE_ID"
  assert rows[0].definition == "Beneficiary identifier, also known as beneficiary id, 2020"
  assert rows[0].aliases == "beneficiary id"
  assert rows[0].years == "2020"
  assert rows[0].page == 3
  assert rows[0].chunk_id == "chunk-1"


def test_extract_variables_from_html_pipe_table_row() -> None:
  chunk = ChunkMetadata(
    chunk_id="chunk-1",
    source_document="/tmp/source.html",
    page=None,
    text="| 1 | BENE_ID | CCW Encrypted Beneficiary ID Number |",
    dataset="medpar",
    url="https://resdac.org/cms-data/files/medpar/data-documentation",
  )

  rows, skipped = extract_variables_from_chunk(chunk)

  assert skipped == 0
  assert len(rows) == 1
  assert rows[0].variable_id == "medpar__var__bene-id"
  assert rows[0].definition == "CCW Encrypted Beneficiary ID Number"


def test_deduplicate_variables_prefers_html_data_documentation() -> None:
  pdf_row = VariableMetadataRow(
    variable_id="medpar__var__bene-id",
    variable_name="BENE_ID",
    dataset_id="medpar",
    definition=(
      "A longer PDF definition that should lose when HTML data documentation "
      "exists for the same variable."
    ),
    source_document="data/raw/assets/pdf/codebook.pdf",
    source_url="https://www2.ccwdata.org/documents/codebook.pdf",
    page=33,
    chunk_id="pdf-chunk",
  )
  html_row = VariableMetadataRow(
    variable_id="medpar__var__bene-id",
    variable_name="BENE_ID",
    dataset_id="medpar",
    definition="CCW Encrypted Beneficiary ID Number",
    source_document="data/raw/html/documentation_page/medpar.html",
    source_url="https://resdac.org/cms-data/files/medpar/data-documentation",
    page=None,
    chunk_id="html-chunk",
  )

  rows = _deduplicate_variables([pdf_row, html_row])

  assert rows == [html_row]


def test_deduplicate_variables_keeps_longer_definition_with_same_priority() -> None:
  short_row = VariableMetadataRow(
    variable_id="mbsf__var__bene-id",
    variable_name="BENE_ID",
    dataset_id="mbsf",
    definition="Beneficiary ID",
    source_document="data/raw/html/documentation_page/mbsf.html",
    source_url="https://resdac.org/cms-data/files/mbsf/data-documentation",
    page=None,
    chunk_id="short-chunk",
  )
  long_row = VariableMetadataRow(
    variable_id="mbsf__var__bene-id",
    variable_name="BENE_ID",
    dataset_id="mbsf",
    definition="Encrypted CCW Beneficiary ID",
    source_document="data/raw/html/documentation_page/mbsf.html",
    source_url="https://resdac.org/cms-data/files/mbsf/data-documentation",
    page=None,
    chunk_id="long-chunk",
  )

  rows = _deduplicate_variables([short_row, long_row])

  assert rows == [long_row]


def test_read_chunks_jsonl_reports_malformed_rows(tmp_path: Path) -> None:
  input_path = tmp_path / "chunks.jsonl"
  source_path = tmp_path / "source.txt"
  source_path.write_text("source", encoding="utf-8")
  valid_chunk = ChunkMetadata(
    chunk_id="chunk-1",
    source_document=str(source_path),
    page=None,
    text="BENE_ID: Beneficiary identifier.",
    dataset="mbsf",
    url="https://resdac.org/cms-data/files/mbsf",
  )
  input_path.write_text(
    valid_chunk.model_dump_json() + "\n{not-json}\n",
    encoding="utf-8",
  )

  chunks, failures = read_chunks_jsonl(input_path)

  assert len(chunks) == 1
  assert len(failures) == 1
  assert failures[0].chunk_id == "line-2"
  assert "failed to parse chunk JSON" in failures[0].reason


def test_run_variable_extraction_writes_outputs(tmp_path: Path) -> None:
  source_path = tmp_path / "data" / "parsed" / "html" / "mbsf.txt"
  source_path.parent.mkdir(parents=True, exist_ok=True)
  source_path.write_text("source text", encoding="utf-8")
  chunks_path = tmp_path / "data" / "parsed" / "chunks.jsonl"
  _write_chunk_jsonl(
    chunks_path,
    [
      ChunkMetadata(
        chunk_id="chunk-1",
        source_document=str(source_path),
        page=None,
        text="BENE_ID: Beneficiary identifier.",
        dataset="mbsf",
        url="https://resdac.org/cms-data/files/mbsf",
      ),
      ChunkMetadata(
        chunk_id="chunk-2",
        source_document=str(source_path),
        page=None,
        text="BENE_ID: A longer beneficiary identifier definition for dedupe.",
        dataset="mbsf",
        url="https://resdac.org/cms-data/files/mbsf",
      ),
    ],
  )

  result, summary_path = run_variable_extraction(
    VariableExtractionConfig(
      chunks_jsonl_path=chunks_path,
      metadata_dir=tmp_path / "data" / "metadata",
      graph_dir=tmp_path / "data" / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.variable_count == 1
  assert result.edge_count == 1
  assert result.failure_count == 0
  assert summary_path.exists()

  with (tmp_path / "data" / "metadata" / "variables.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    variables = list(csv.DictReader(handle))
  assert variables == [
    {
      "variable_id": "mbsf__var__bene-id",
      "variable_name": "BENE_ID",
      "dataset_id": "mbsf",
      "definition": "A longer beneficiary identifier definition for dedupe",
      "aliases": "",
      "years": "",
      "source_document": str(source_path),
      "source_url": "https://resdac.org/cms-data/files/mbsf",
      "page": "",
      "chunk_id": "chunk-2",
      "extraction_notes": "",
    }
  ]

  with (tmp_path / "data" / "graph" / "variable_edges.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    edges = list(csv.DictReader(handle))
  assert edges[0]["source_id"] == "mbsf"
  assert edges[0]["target_id"] == "mbsf__var__bene-id"
  assert edges[0]["relationship"] == "contains"


def test_run_variable_extraction_writes_canonical_variable_graph(
  tmp_path: Path,
) -> None:
  source_path = tmp_path / "data" / "parsed" / "html" / "mbsf.txt"
  source_path.parent.mkdir(parents=True, exist_ok=True)
  source_path.write_text("source text", encoding="utf-8")
  chunks_path = tmp_path / "data" / "parsed" / "chunks.jsonl"
  _write_chunk_jsonl(
    chunks_path,
    [
      ChunkMetadata(
        chunk_id="chunk-1",
        source_document=str(source_path),
        page=None,
        text="BENE_ID: Beneficiary identifier.",
        dataset="mbsf",
        url="https://resdac.org/cms-data/files/mbsf/data-documentation",
      )
    ],
  )

  variable_page = (
    tmp_path
    / "data"
    / "raw"
    / "html"
    / "variable_page"
    / "encrypted-ccw-beneficiary-id.html"
  )
  variable_html = """
  <html><head><title>Encrypted CCW Beneficiary ID | ResDAC</title></head>
  <body>
    <h1>Encrypted CCW Beneficiary ID</h1>
    <table>
      <tr><th>SAS Name</th><td>BENE_ID</td></tr>
      <tr><th>Definition</th><td>The unique CCW identifier for a beneficiary.</td></tr>
    </table>
    <a href="/cms-data/files/mbsf/data-documentation">MBSF Base</a>
    <a href="/cms-data/files/medpar/data-documentation">MedPAR</a>
  </body></html>
  """
  variable_page.parent.mkdir(parents=True, exist_ok=True)
  variable_page.write_text(variable_html, encoding="utf-8")
  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  write_archive_manifest(
    [
      ArchiveManifestRow(
        url="https://resdac.org/cms-data/variables/encrypted-ccw-beneficiary-id",
        resource_kind="variable_page",
        content_type="text/html",
        http_status=200,
        archive_state="archived",
        downloaded_at_utc="2026-06-16T00:00:00Z",
        sha256=hashlib.sha256(variable_html.encode("utf-8")).hexdigest(),
        local_path=str(variable_page),
      )
    ],
    manifest_path,
  )

  result, _ = run_variable_extraction(
    VariableExtractionConfig(
      chunks_jsonl_path=chunks_path,
      archive_manifest_path=manifest_path,
      metadata_dir=tmp_path / "data" / "metadata",
      graph_dir=tmp_path / "data" / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.canonical_variable_count == 1
  assert result.canonical_variables[0].variable_id == "encrypted-ccw-beneficiary-id"
  assert result.canonical_variables[0].variable_name == "BENE_ID"
  assert result.data_source_variable_edge_count == 2
  assert {
    edge.source_id for edge in result.data_source_variable_edges
  } == {"mbsf", "medpar"}

  with (tmp_path / "data" / "metadata" / "canonical_variables.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    canonical_rows = list(csv.DictReader(handle))
  assert canonical_rows[0]["variable_id"] == "encrypted-ccw-beneficiary-id"

  with (tmp_path / "data" / "graph" / "data_source_variable_edges.csv").open(
    newline="", encoding="utf-8"
  ) as handle:
    edge_rows = list(csv.DictReader(handle))
  assert len(edge_rows) == 2


def test_run_variable_extraction_reports_missing_source_document(
  tmp_path: Path,
) -> None:
  chunks_path = tmp_path / "chunks.jsonl"
  _write_chunk_jsonl(
    chunks_path,
    [
      ChunkMetadata(
        chunk_id="chunk-1",
        source_document=str(tmp_path / "missing.txt"),
        page=None,
        text="BENE_ID: Beneficiary identifier.",
        dataset="mbsf",
        url="https://resdac.org/cms-data/files/mbsf",
      )
    ],
  )

  result, _ = run_variable_extraction(
    VariableExtractionConfig(
      chunks_jsonl_path=chunks_path,
      metadata_dir=tmp_path / "metadata",
      graph_dir=tmp_path / "graph",
      workspace_dir=tmp_path / "_workspace",
    )
  )

  assert result.variable_count == 0
  assert result.failure_count == 1
  assert result.failures[0].reason == "source_document does not exist locally"


def test_variable_cli_success(tmp_path: Path) -> None:
  source_path = tmp_path / "source.txt"
  source_path.write_text("source", encoding="utf-8")
  chunks_path = tmp_path / "chunks.jsonl"
  _write_chunk_jsonl(
    chunks_path,
    [
      ChunkMetadata(
        chunk_id="chunk-1",
        source_document=str(source_path),
        page=1,
        text="CLM_ID: Claim identifier.",
        dataset="carrier",
        url="https://resdac.org/cms-data/files/carrier",
      )
    ],
  )

  exit_code = main([
    "--chunks-jsonl",
    str(chunks_path),
    "--metadata-dir",
    str(tmp_path / "metadata"),
    "--graph-dir",
    str(tmp_path / "graph"),
    "--workspace-dir",
    str(tmp_path / "_workspace"),
  ])

  assert exit_code == 0
  assert (tmp_path / "metadata" / "variables.csv").exists()


def test_variable_cli_failure_for_missing_input(tmp_path: Path) -> None:
  exit_code = main([
    "--chunks-jsonl",
    str(tmp_path / "missing.jsonl"),
    "--metadata-dir",
    str(tmp_path / "metadata"),
    "--graph-dir",
    str(tmp_path / "graph"),
    "--workspace-dir",
    str(tmp_path / "_workspace"),
  ])

  assert exit_code == 1
