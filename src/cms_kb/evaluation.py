"""Small retrieval usefulness evaluation helpers for CMS KB variables.

This module provides the validation logic to assess the quality of variables
retrieval in the CMS Knowledge Base. It randomly samples variables (with a stable random
seed) and runs queries to check if the retrieval system:
1. Surfaces the correct variable in the top N search ranks.
2. Exposes actual "definition evidence" inside the snippet (meaningful tokens rather
   than just repeating the variable ID or title).
3. Preserves traceability through a valid web source citation.
4. Prefers HTML source pages over PDF or Excel assets when both are available,
   since HTML is typically the canonical variable detail page at ResDAC.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from .retrieval import RetrievalConfig, SearchResult, run_retrieval
from .variables import VariableMetadataRow


class VariableEvaluationConfig(BaseModel):
  """Configuration settings for variable retrieval evaluation.

  Attributes:
    retrieval: Settings configuration for locating variables metadata and chunks files.
    sample_size: Number of unique variable names to randomly sample.
    seed: RNG seed to ensure repeatable, deterministic evaluation runs.
    limit: The maximum search rank depth to check for a successful match.
  """
  retrieval: RetrievalConfig = RetrievalConfig()
  sample_size: int = 10
  seed: int = 20260616
  limit: int = 5


class VariableEvaluationCase(BaseModel):
  """Results of evaluating retrieval for a single variable name.

  Attributes:
    variable_name: The name of the variable query being tested.
    expected_variable_ids: Target variable IDs associated with this variable name.
    expected_dataset_ids: Target dataset IDs that contain this variable.
    top_result: The very first retrieval match returned.
    first_matching_rank: The 1-based rank where the expected variable record first appeared.
    first_matching_result: The matched SearchResult record itself.
    snippet_has_definition_evidence: True if the result snippet includes contextual words.
    citation_present: True if the result includes a citation web URL.
    html_preferred_when_available: True if the query returned an HTML record or HTML wasn't available.
    html_evidence_available: True if any source metadata rows originate from HTML.
    passed: Overall boolean indicating whether all quality checks were satisfied.
  """
  variable_name: str
  expected_variable_ids: list[str]
  expected_dataset_ids: list[str]
  top_result: SearchResult | None = None
  first_matching_rank: int | None = None
  first_matching_result: SearchResult | None = None
  snippet_has_definition_evidence: bool = False
  citation_present: bool = False
  html_preferred_when_available: bool = False
  html_evidence_available: bool = False
  passed: bool = False


class VariableEvaluationReport(BaseModel):
  """The compiled results report for a complete evaluation run.

  Attributes:
    sample_size: Total number of cases evaluated.
    seed: The random seed used for sampling.
    limit: The retrieval limit cutoff used.
    cases: Details for each individual variable name case.
  """
  sample_size: int
  seed: int
  limit: int
  cases: list[VariableEvaluationCase] = Field(default_factory=list)

  @property
  def passed_count(self) -> int:
    """The total number of cases that successfully passed all checks."""
    return sum(1 for case in self.cases if case.passed)

  @property
  def pass_rate(self) -> float:
    """Ratio of passed cases to the total sample size."""
    if not self.cases:
      return 0.0
    return self.passed_count / len(self.cases)


def _read_variable_rows(path: Path) -> list[VariableMetadataRow]:
  with path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"variables CSV has no header: {path}")
    rows: list[VariableMetadataRow] = []
    for row in reader:
      page_value = row.get("page", "").strip()
      payload: dict[str, object] = dict(row)
      payload["page"] = int(page_value) if page_value else None
      rows.append(VariableMetadataRow.model_validate(payload))
    return rows


def _sample_variable_names(
  rows: list[VariableMetadataRow],
  sample_size: int,
  seed: int,
) -> list[str]:
  if sample_size <= 0:
    raise ValueError("sample_size must be greater than 0")
  names = sorted({row.variable_name for row in rows if row.variable_name.strip()})
  if not names:
    return []
  rng = random.Random(seed)
  if sample_size >= len(names):
    return names
  return sorted(rng.sample(names, sample_size))


def _snippet_has_definition_evidence(result: SearchResult) -> bool:
  """Checks if a search match snippet actually contains contextual text.

  To prevent false positives where the snippet only contains the queried variable
  name or its ID without any descriptive definition, this function filters out
  those tokens and checks if at least 3 other non-numeric words remain.
  """
  snippet_tokens = {
    token.lower()
    for token in [
      result.record_id,
      result.title,
      result.dataset_id,
    ]
    if token
  }
  words = [
    word
    for word in result.snippet.replace("_", " ").replace("-", " ").split()
    if word.strip(" .,:;|()").lower() not in snippet_tokens
  ]
  meaningful_words = [
    word
    for word in words
    if len(word.strip(" .,:;|()")) > 2 and not word.strip(" .,:;|()").isdigit()
  ]
  return len(meaningful_words) >= 3


def _is_html_result(result: SearchResult) -> bool:
  source_document = result.source_document.lower()
  return source_document.endswith(".html") or "/data-documentation" in result.source_url.lower()


def _html_evidence_available(rows: list[VariableMetadataRow]) -> bool:
  return any(
    row.source_document.lower().endswith(".html")
    or "/data-documentation" in row.source_url.lower()
    for row in rows
  )


def _evaluate_variable_name(
  config: RetrievalConfig,
  variable_name: str,
  rows: list[VariableMetadataRow],
  limit: int,
) -> VariableEvaluationCase:
  """Runs evaluation checks for a specific variable name query.

  Queries the retrieval system with the variable name, maps the matches, and evaluates
  whether the returned results satisfy all qualitative criteria.
  """
  expected_variable_ids = sorted({row.variable_id for row in rows})
  expected_dataset_ids = sorted({row.dataset_id for row in rows})
  html_available = _html_evidence_available(rows)
  results = run_retrieval(config, variable_name, limit=limit)
  matching_results = [
    (index, result)
    for index, result in enumerate(results, start=1)
    if result.record_id in expected_variable_ids and result.record_type == "variable"
  ]
  first_matching_rank = matching_results[0][0] if matching_results else None
  first_matching_result = matching_results[0][1] if matching_results else None
  citation_present = (
    first_matching_result is not None and bool(first_matching_result.source_url.strip())
  )
  snippet_has_definition_evidence = (
    first_matching_result is not None
    and _snippet_has_definition_evidence(first_matching_result)
  )
  html_preferred_when_available = (
    not html_available
    or (first_matching_result is not None and _is_html_result(first_matching_result))
  )
  passed = (
    first_matching_rank is not None
    and first_matching_rank <= limit
    and citation_present
    and snippet_has_definition_evidence
    and html_preferred_when_available
  )
  return VariableEvaluationCase(
    variable_name=variable_name,
    expected_variable_ids=expected_variable_ids,
    expected_dataset_ids=expected_dataset_ids,
    top_result=results[0] if results else None,
    first_matching_rank=first_matching_rank,
    first_matching_result=first_matching_result,
    snippet_has_definition_evidence=snippet_has_definition_evidence,
    citation_present=citation_present,
    html_preferred_when_available=html_preferred_when_available,
    html_evidence_available=html_available,
    passed=passed,
  )


def evaluate_variable_retrieval(config: VariableEvaluationConfig) -> VariableEvaluationReport:
  """Runs the full seeded evaluation suite across the variable metadata catalog.

  Args:
    config: VariableEvaluationConfig configuration parameters.

  Returns:
    A VariableEvaluationReport mapping outcomes across all sampled cases.
  """
  rows = _read_variable_rows(config.retrieval.variables_metadata_path)
  rows_by_name: dict[str, list[VariableMetadataRow]] = {}
  for row in rows:
    rows_by_name.setdefault(row.variable_name, []).append(row)

  sampled_names = _sample_variable_names(rows, config.sample_size, config.seed)
  cases = [
    _evaluate_variable_name(
      config.retrieval,
      variable_name,
      rows_by_name[variable_name],
      config.limit,
    )
    for variable_name in sampled_names
  ]
  return VariableEvaluationReport(
    sample_size=len(cases),
    seed=config.seed,
    limit=config.limit,
    cases=cases,
  )


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Evaluate exact variable-name retrieval usefulness with a seeded sample."
  )
  parser.add_argument("--sample-size", type=int, default=10)
  parser.add_argument("--seed", type=int, default=20260616)
  parser.add_argument("--limit", type=int, default=5)
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
  config = VariableEvaluationConfig(
    retrieval=RetrievalConfig(
      datasets_metadata_path=args.datasets_metadata,
      documents_metadata_path=args.documents_metadata,
      variables_metadata_path=args.variables_metadata,
      chunks_jsonl_path=args.chunks_jsonl,
    ),
    sample_size=args.sample_size,
    seed=args.seed,
    limit=args.limit,
  )

  try:
    report = evaluate_variable_retrieval(config)
  except Exception as exc:
    print(f"Error executing variable retrieval evaluation: {exc}", file=sys.stderr)
    return 1

  if args.json:
    payload = report.model_dump()
    payload["passed_count"] = report.passed_count
    payload["pass_rate"] = report.pass_rate
    print(json.dumps(payload, indent=2))
    return 0 if report.passed_count == report.sample_size else 1

  print(
    f"variable retrieval usefulness: {report.passed_count}/{report.sample_size} "
    f"passed (seed={report.seed}, limit={report.limit})"
  )
  for case in report.cases:
    status = "PASS" if case.passed else "FAIL"
    rank = case.first_matching_rank if case.first_matching_rank is not None else "-"
    print(f"{status}\t{case.variable_name}\trank={rank}")
  return 0 if report.passed_count == report.sample_size else 1


__all__ = [
  "VariableEvaluationCase",
  "VariableEvaluationConfig",
  "VariableEvaluationReport",
  "build_arg_parser",
  "evaluate_variable_retrieval",
  "main",
]
