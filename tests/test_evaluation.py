from __future__ import annotations

import csv
import json
from pathlib import Path

from cms_kb.evaluation import (
  BenchmarkQuestion,
  BenchmarkQuestionSuite,
  VariableEvaluationConfig,
  evaluate_benchmark_suite,
  evaluate_variable_retrieval,
  main,
  recall_at_k,
  reciprocal_rank,
  citation_accuracy,
)
from cms_kb.parsing import ChunkMetadata
from cms_kb.retrieval import RetrievalConfig, build_index


def _write_evaluation_fixture(tmp_path: Path) -> RetrievalConfig:
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
      "medpar",
      "MedPAR",
      "Medicare",
      "Claims",
      "Available",
      "https://resdac.org/cms-data/files/medpar",
      str(tmp_path / "raw" / "medpar.html"),
      "fake-sha",
      "",
    ])
    writer.writerow([
      "pde",
      "PDE",
      "Medicare",
      "Part D",
      "Available",
      "https://resdac.org/cms-data/files/pde",
      str(tmp_path / "raw" / "pde.html"),
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

  variables_csv = metadata_dir / "variables.csv"
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
      "medpar__var__bene-id",
      "BENE_ID",
      "medpar",
      "CCW Encrypted Beneficiary ID Number",
      "",
      "",
      str(tmp_path / "raw" / "medpar-data.html"),
      "https://resdac.org/cms-data/files/medpar/data-documentation",
      "",
      "chunk-1",
      "",
    ])
    writer.writerow([
      "pde__var__pde-id",
      "PDE_ID",
      "pde",
      "Prescription drug event identifier",
      "",
      "",
      str(tmp_path / "raw" / "pde-data.html"),
      "https://resdac.org/cms-data/files/pde/data-documentation",
      "",
      "chunk-2",
      "",
    ])

  chunks_jsonl = parsed_dir / "chunks.jsonl"
  chunks = [
    ChunkMetadata(
      chunk_id="chunk-1",
      source_document=str(tmp_path / "raw" / "medpar-data.html"),
      page=None,
      text="| BENE_ID | CCW Encrypted Beneficiary ID Number |",
      dataset="medpar",
      url="https://resdac.org/cms-data/files/medpar/data-documentation",
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


def test_evaluate_variable_retrieval_uses_seeded_sample(tmp_path: Path) -> None:
  retrieval = _write_evaluation_fixture(tmp_path)
  config = VariableEvaluationConfig(
    retrieval=retrieval,
    sample_size=1,
    seed=20260616,
    limit=5,
  )

  first_report = evaluate_variable_retrieval(config)
  second_report = evaluate_variable_retrieval(config)

  assert [case.variable_name for case in first_report.cases] == [
    case.variable_name for case in second_report.cases
  ]
  assert first_report.sample_size == 1
  assert first_report.cases[0].passed
  assert first_report.cases[0].first_matching_rank == 1
  assert first_report.cases[0].citation_present


def test_evaluation_cli_outputs_json(tmp_path: Path, capsys) -> None:
  retrieval = _write_evaluation_fixture(tmp_path)

  exit_code = main([
    "--sample-size",
    "1",
    "--seed",
    "20260616",
    "--datasets-metadata",
    str(retrieval.datasets_metadata_path),
    "--documents-metadata",
    str(retrieval.documents_metadata_path),
    "--variables-metadata",
    str(retrieval.variables_metadata_path),
    "--chunks-jsonl",
    str(retrieval.chunks_jsonl_path),
    "--database-path",
    str(retrieval.database_path),
    "--json",
  ])

  captured = capsys.readouterr()
  payload = json.loads(captured.out)
  assert exit_code == 0
  assert payload["sample_size"] == 1
  assert payload["passed_count"] == 1
  assert payload["pass_rate"] == 1.0


def test_evaluation_metrics_calculations() -> None:
  # 1. Recall
  assert recall_at_k(["a", "b", "c"], ["a", "d"], k=2) == 0.5
  assert recall_at_k(["a", "b", "c"], ["a", "b"], k=2) == 1.0
  assert recall_at_k(["a", "b", "c"], [], k=5) == 1.0

  # 2. Reciprocal Rank
  assert reciprocal_rank(["a", "b", "c"], ["b", "d"]) == 0.5
  assert reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0
  assert reciprocal_rank(["a", "b", "c"], ["d"]) == 0.0
  assert reciprocal_rank(["a", "b", "c"], []) == 1.0

  # 3. Citation Accuracy
  assert citation_accuracy(["http://a.com/", "http://b.com"], ["http://a.com"]) == 1.0
  assert citation_accuracy(["http://a.com"], ["http://a.com", "http://b.com"]) == 0.5
  assert citation_accuracy([], []) == 1.0


def test_evaluate_benchmark_suite(tmp_path: Path) -> None:
  retrieval = _write_evaluation_fixture(tmp_path)
  
  # Create a dummy archive manifest file
  archive_manifest = tmp_path / "archive_manifest.csv"
  archive_manifest.write_text("local_path,url,downloaded_at,sha256,content_type\n", encoding="utf-8")

  # Write dummy benchmark questions JSON
  benchmark_questions = [
    {
      "question_id": "q1",
      "query": "BENE_ID",
      "expected_datasets": ["medpar"],
      "expected_variables": ["BENE_ID"],
      "expected_citations": ["https://resdac.org/cms-data/files/medpar/data-documentation"],
      "description": "Test dual eligibility query"
    }
  ]
  benchmark_file = tmp_path / "benchmark_questions.json"
  benchmark_file.write_text(json.dumps(benchmark_questions), encoding="utf-8")

  config = VariableEvaluationConfig(
    retrieval=retrieval,
    sample_size=1,
    seed=20260616,
    limit=5,
  )

  suite = BenchmarkQuestionSuite(
    questions=[BenchmarkQuestion.model_validate(q) for q in benchmark_questions]
  )

  # Monkey patch Path("manifests/archive_manifest.csv") resolution
  import cms_kb.evaluation as ev
  ev_manifest_backup = ev.Path
  
  class MockPathClass:
    def __new__(cls, *args, **kwargs):
      # Redirect specific check to tmp_path
      path_str = str(args[0]) if args else ""
      if "archive_manifest.csv" in path_str:
        return Path(archive_manifest)
      return Path(*args, **kwargs)

  ev.Path = MockPathClass  # pytype: disable=name-error

  try:
    report = evaluate_benchmark_suite(config, suite)
    assert len(report.results) == 1
    assert report.results[0].question_id == "q1"
    assert report.results[0].lexical.dataset_recall_at_5 == 1.0
  finally:
    ev.Path = ev_manifest_backup


def test_evaluation_cli_benchmark_option(tmp_path: Path) -> None:
  retrieval = _write_evaluation_fixture(tmp_path)

  # Create a dummy archive manifest file
  archive_manifest = tmp_path / "archive_manifest.csv"
  archive_manifest.write_text("local_path,url,downloaded_at,sha256,content_type\n", encoding="utf-8")

  # Write dummy benchmark questions JSON
  benchmark_questions = [
    {
      "question_id": "q1",
      "query": "BENE_ID",
      "expected_datasets": ["medpar"],
      "expected_variables": ["BENE_ID"],
      "expected_citations": ["https://resdac.org/cms-data/files/medpar/data-documentation"],
      "description": "Test dual eligibility query"
    }
  ]
  benchmark_file = tmp_path / "benchmark_questions.json"
  benchmark_file.write_text(json.dumps(benchmark_questions), encoding="utf-8")
  output_report = tmp_path / "report.md"

  import cms_kb.evaluation as ev
  ev_manifest_backup = ev.Path
  
  class MockPathClass:
    def __new__(cls, *args, **kwargs):
      path_str = str(args[0]) if args else ""
      if "archive_manifest.csv" in path_str:
        return Path(archive_manifest)
      return Path(*args, **kwargs)

  ev.Path = MockPathClass  # pytype: disable=name-error

  try:
    exit_code = main([
      "--datasets-metadata",
      str(retrieval.datasets_metadata_path),
      "--documents-metadata",
      str(retrieval.documents_metadata_path),
      "--variables-metadata",
      str(retrieval.variables_metadata_path),
      "--chunks-jsonl",
      str(retrieval.chunks_jsonl_path),
      "--database-path",
      str(retrieval.database_path),
      "--benchmark",
      str(benchmark_file),
      "--output-report",
      str(output_report),
    ])
    assert exit_code == 0
    assert output_report.is_file()
    assert "Aggregate Benchmark Summary" in output_report.read_text(encoding="utf-8")
  finally:
    ev.Path = ev_manifest_backup

