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

from .paths import get_packaged_data_path
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


# --- Benchmark Suite Models and Metrics (Phase 12) ---

class BenchmarkQuestion(BaseModel):
  """A gold-standard benchmark query with expected ground truth search hits."""
  question_id: str
  query: str
  expected_datasets: list[str] = Field(default_factory=list)
  expected_variables: list[str] = Field(default_factory=list)
  expected_documents: list[str] = Field(default_factory=list)
  expected_citations: list[str] = Field(default_factory=list)
  description: str = ""


class BenchmarkQuestionSuite(BaseModel):
  """A collection of benchmark questions."""
  questions: list[BenchmarkQuestion]


class PathEvaluationResult(BaseModel):
  """Evaluation metrics for a single search path for a benchmark question."""
  dataset_recall_at_5: float
  variable_recall_at_5: float
  citation_accuracy: float
  dataset_mrr: float
  variable_mrr: float


class QuestionEvaluationResult(BaseModel):
  """Comparison of evaluation metrics across all three search paths for a single question."""
  question_id: str
  query: str
  lexical: PathEvaluationResult
  hybrid: PathEvaluationResult
  agent_facing: PathEvaluationResult


class BenchmarkReport(BaseModel):
  """The compiled benchmark results report across a suite of questions."""
  mean_lexical: PathEvaluationResult
  mean_hybrid: PathEvaluationResult
  mean_agent_facing: PathEvaluationResult
  results: list[QuestionEvaluationResult] = Field(default_factory=list)


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
  """Calculates Recall@K: proportion of expected IDs found in top K retrieved IDs."""
  if not expected:
    return 1.0
  top_k = retrieved[:k]
  matched = set(top_k) & set(expected)
  return len(matched) / len(expected)


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float:
  """Calculates Reciprocal Rank (RR): 1 / rank of the first correct retrieved ID."""
  if not expected:
    return 1.0
  for index, item in enumerate(retrieved):
    if item in expected:
      return 1.0 / (index + 1)
  return 0.0


def citation_accuracy(retrieved: list[str], expected: list[str]) -> float:
  """Calculates Citation Accuracy: fraction of expected citations present in retrieved citations."""
  if not expected:
    return 1.0

  def normalize(url: str) -> str:
    return url.strip().rstrip("/").lower()

  norm_retrieved = {normalize(c) for c in retrieved if c}
  norm_expected = {normalize(e) for e in expected if e}

  matched = norm_retrieved & norm_expected
  return len(matched) / len(norm_expected)


def extract_lexical_hybrid_ids(results: list[SearchResult]) -> tuple[list[str], list[str], list[str]]:
  """Extracts dataset IDs, variable identifiers, and citations from SearchResults."""
  retrieved_datasets = []
  retrieved_variables = []
  retrieved_citations = []
  for r in results:
    if r.record_type == "dataset":
      retrieved_datasets.append(r.record_id)
    elif r.dataset_id:
      retrieved_datasets.append(r.dataset_id)

    if r.record_type == "variable":
      retrieved_variables.append(r.record_id)
      retrieved_variables.append(r.title)

    if r.source_url:
      retrieved_citations.append(r.source_url)
  return retrieved_datasets, retrieved_variables, retrieved_citations


def evaluate_path(
  retrieved_datasets: list[str],
  retrieved_variables: list[str],
  retrieved_citations: list[str],
  question: BenchmarkQuestion,
) -> PathEvaluationResult:
  """Computes PathEvaluationResult for a set of retrieved entities and expected outputs."""
  return PathEvaluationResult(
    dataset_recall_at_5=recall_at_k(retrieved_datasets, question.expected_datasets, 5),
    variable_recall_at_5=recall_at_k(retrieved_variables, question.expected_variables, 5),
    citation_accuracy=citation_accuracy(retrieved_citations, question.expected_citations),
    dataset_mrr=reciprocal_rank(retrieved_datasets, question.expected_datasets),
    variable_mrr=reciprocal_rank(retrieved_variables, question.expected_variables),
  )


def evaluate_benchmark_suite(
  config: VariableEvaluationConfig,
  suite: BenchmarkQuestionSuite,
) -> BenchmarkReport:
  """Runs the benchmark suite queries over Lexical, Hybrid, and Agent-facing paths."""
  from .agent_api import AgentContextConfig, build_agent_context

  results: list[QuestionEvaluationResult] = []
  archive_manifest_path = Path("manifests/archive_manifest.csv")

  for question in suite.questions:
    # 1. Lexical Path
    lex_config = RetrievalConfig.model_validate(config.retrieval.model_dump())
    lex_config.hybrid_search_enabled = False
    lex_search_results = run_retrieval(lex_config, question.query, limit=10)
    lex_d, lex_v, lex_c = extract_lexical_hybrid_ids(lex_search_results)
    lex_res = evaluate_path(lex_d, lex_v, lex_c, question)

    # 2. Hybrid Path
    hybrid_config = RetrievalConfig.model_validate(config.retrieval.model_dump())
    hybrid_config.hybrid_search_enabled = True
    hybrid_search_results = run_retrieval(hybrid_config, question.query, limit=10)
    hybrid_d, hybrid_v, hybrid_c = extract_lexical_hybrid_ids(hybrid_search_results)
    hybrid_res = evaluate_path(hybrid_d, hybrid_v, hybrid_c, question)

    # 3. Agent-facing Path
    agent_config = AgentContextConfig(
      retrieval=config.retrieval,
      archive_manifest_path=archive_manifest_path,
      default_limit=10,
    )
    agent_response = build_agent_context(agent_config, question.query, limit=10)
    
    agent_d = []
    agent_v = []
    agent_c = []
    for h in agent_response.results:
      if h.record_type == "dataset":
        agent_d.append(h.record_id)
      elif h.dataset_id:
        agent_d.append(h.dataset_id)

      if h.record_type == "variable":
        agent_v.append(h.record_id)
        agent_v.append(h.title)

      if h.citation:
        if h.citation.source_url:
          agent_c.append(h.citation.source_url)
        if h.citation.variable_url:
          agent_c.append(h.citation.variable_url)
          
    agent_res = evaluate_path(agent_d, agent_v, agent_c, question)

    results.append(
      QuestionEvaluationResult(
        question_id=question.question_id,
        query=question.query,
        lexical=lex_res,
        hybrid=hybrid_res,
        agent_facing=agent_res,
      )
    )

  def average(field: str, path: str) -> float:
    vals = []
    for r in results:
      p_res = getattr(r, path)
      vals.append(getattr(p_res, field))
    return sum(vals) / len(vals) if vals else 1.0

  def make_mean_result(path: str) -> PathEvaluationResult:
    return PathEvaluationResult(
      dataset_recall_at_5=average("dataset_recall_at_5", path),
      variable_recall_at_5=average("variable_recall_at_5", path),
      citation_accuracy=average("citation_accuracy", path),
      dataset_mrr=average("dataset_mrr", path),
      variable_mrr=average("variable_mrr", path),
    )

  return BenchmarkReport(
    mean_lexical=make_mean_result("lexical"),
    mean_hybrid=make_mean_result("hybrid"),
    mean_agent_facing=make_mean_result("agent_facing"),
    results=results,
  )


def generate_markdown_report(report: BenchmarkReport, output_path: Path) -> None:
  """Saves a markdown report comparing performance across search paths."""
  output_path.parent.mkdir(parents=True, exist_ok=True)

  lines = [
    "# Retrieval Performance Evaluation Report",
    "",
    "This report compares the retrieval and citation performance of three search paths:",
    "- **Lexical**: SQLite FTS5 search.",
    "- **Hybrid**: SQLite FTS5 + semantic reranking (all-MiniLM-L6-v2 embeddings).",
    "- **Agent-facing**: Pydantic context response API with citation resolving.",
    "",
    "## Aggregate Benchmark Summary",
    "",
    "| Metric | Lexical | Hybrid | Agent-facing |",
    "| :--- | :---: | :---: | :---: |",
    f"| **Dataset Recall@5** | {report.mean_lexical.dataset_recall_at_5:.2%} | {report.mean_hybrid.dataset_recall_at_5:.2%} | {report.mean_agent_facing.dataset_recall_at_5:.2%} |",
    f"| **Variable Recall@5** | {report.mean_lexical.variable_recall_at_5:.2%} | {report.mean_hybrid.variable_recall_at_5:.2%} | {report.mean_agent_facing.variable_recall_at_5:.2%} |",
    f"| **Citation Accuracy** | {report.mean_lexical.citation_accuracy:.2%} | {report.mean_hybrid.citation_accuracy:.2%} | {report.mean_agent_facing.citation_accuracy:.2%} |",
    f"| **Dataset MRR** | {report.mean_lexical.dataset_mrr:.4f} | {report.mean_hybrid.dataset_mrr:.4f} | {report.mean_agent_facing.dataset_mrr:.4f} |",
    f"| **Variable MRR** | {report.mean_lexical.variable_mrr:.4f} | {report.mean_hybrid.variable_mrr:.4f} | {report.mean_agent_facing.variable_mrr:.4f} |",
    "",
    "## Per-Question Results Comparison",
    "",
  ]

  for r in report.results:
    lines.extend([
      f"### Query: `{r.query}` (ID: {r.question_id})",
      "",
      "| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |",
      "| :--- | :---: | :---: | :---: | :---: | :---: |",
      f"| **Lexical** | {r.lexical.dataset_recall_at_5:.2%} | {r.lexical.variable_recall_at_5:.2%} | {r.lexical.citation_accuracy:.2%} | {r.lexical.dataset_mrr:.4f} | {r.lexical.variable_mrr:.4f} |",
      f"| **Hybrid** | {r.hybrid.dataset_recall_at_5:.2%} | {r.hybrid.variable_recall_at_5:.2%} | {r.hybrid.citation_accuracy:.2%} | {r.hybrid.dataset_mrr:.4f} | {r.hybrid.variable_mrr:.4f} |",
      f"| **Agent-facing** | {r.agent_facing.dataset_recall_at_5:.2%} | {r.agent_facing.variable_recall_at_5:.2%} | {r.agent_facing.citation_accuracy:.2%} | {r.agent_facing.dataset_mrr:.4f} | {r.agent_facing.variable_mrr:.4f} |",
      "",
    ])

  output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    default=get_packaged_data_path("metadata/datasets.csv"),
  )
  parser.add_argument(
    "--documents-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/documents.csv"),
  )
  parser.add_argument(
    "--variables-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/variables.csv"),
  )
  parser.add_argument(
    "--chunks-jsonl",
    type=Path,
    default=get_packaged_data_path("parsed/chunks.jsonl"),
  )
  parser.add_argument(
    "--database-path",
    type=Path,
    default=get_packaged_data_path("index/retrieval.sqlite"),
  )
  parser.add_argument("--json", action="store_true")
  parser.add_argument(
    "--benchmark",
    type=Path,
    nargs="?",
    const=Path("data/evaluation/benchmark_questions.json"),
    default=None,
    help="Path to gold-standard benchmark questions JSON file to run the full comparative evaluation suite.",
  )
  parser.add_argument(
    "--output-report",
    type=Path,
    default=Path("_workspace/retrieval_evaluation_report.md"),
    help="Path where the compiled markdown report comparing the three retrieval paths will be saved.",
  )
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
      database_path=args.database_path,
    ),
    sample_size=args.sample_size,
    seed=args.seed,
    limit=args.limit,
  )

  if args.benchmark is not None:
    benchmark_path = Path(args.benchmark)
    if not benchmark_path.is_file():
      pkg_path = get_packaged_data_path("evaluation/benchmark_questions.json")
      if pkg_path.is_file():
        benchmark_path = pkg_path
      else:
        print(f"Error: benchmark questions file not found at {args.benchmark}", file=sys.stderr)
        return 1

    try:
      with benchmark_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
      suite = BenchmarkQuestionSuite(questions=[BenchmarkQuestion.model_validate(q) for q in data])
      report = evaluate_benchmark_suite(config, suite)
    except Exception as exc:
      print(f"Error executing benchmark evaluation: {exc}", file=sys.stderr)
      return 1

    try:
      generate_markdown_report(report, args.output_report)
    except Exception as exc:
      print(f"Warning: failed to write markdown report to {args.output_report}: {exc}", file=sys.stderr)

    if args.json:
      print(report.model_dump_json(indent=2))
      return 0

    print("CMS Retrieval Benchmark Suite Evaluation")
    print("========================================")
    print("Lexical Path:")
    print(f"  Mean Dataset Recall@5: {report.mean_lexical.dataset_recall_at_5:.2%}")
    print(f"  Mean Variable Recall@5: {report.mean_lexical.variable_recall_at_5:.2%}")
    print(f"  Mean Citation Accuracy: {report.mean_lexical.citation_accuracy:.2%}")
    print(f"  Mean Dataset MRR: {report.mean_lexical.dataset_mrr:.4f}")
    print(f"  Mean Variable MRR: {report.mean_lexical.variable_mrr:.4f}")
    print()
    print("Hybrid Path:")
    print(f"  Mean Dataset Recall@5: {report.mean_hybrid.dataset_recall_at_5:.2%}")
    print(f"  Mean Variable Recall@5: {report.mean_hybrid.variable_recall_at_5:.2%}")
    print(f"  Mean Citation Accuracy: {report.mean_hybrid.citation_accuracy:.2%}")
    print(f"  Mean Dataset MRR: {report.mean_hybrid.dataset_mrr:.4f}")
    print(f"  Mean Variable MRR: {report.mean_hybrid.variable_mrr:.4f}")
    print()
    print("Agent-facing Path:")
    print(f"  Mean Dataset Recall@5: {report.mean_agent_facing.dataset_recall_at_5:.2%}")
    print(f"  Mean Variable Recall@5: {report.mean_agent_facing.variable_recall_at_5:.2%}")
    print(f"  Mean Citation Accuracy: {report.mean_agent_facing.citation_accuracy:.2%}")
    print(f"  Mean Dataset MRR: {report.mean_agent_facing.dataset_mrr:.4f}")
    print(f"  Mean Variable MRR: {report.mean_agent_facing.variable_mrr:.4f}")
    print()
    print(f"Comparative report saved to {args.output_report}")
    return 0

  try:
    var_report = evaluate_variable_retrieval(config)
  except Exception as exc:
    print(f"Error executing variable retrieval evaluation: {exc}", file=sys.stderr)
    return 1

  if args.json:
    payload = var_report.model_dump()
    payload["passed_count"] = var_report.passed_count
    payload["pass_rate"] = var_report.pass_rate
    print(json.dumps(payload, indent=2))
    return 0 if var_report.passed_count == var_report.sample_size else 1

  print(
    f"variable retrieval usefulness: {var_report.passed_count}/{var_report.sample_size} "
    f"passed (seed={var_report.seed}, limit={var_report.limit})"
  )
  for case in var_report.cases:
    status = "PASS" if case.passed else "FAIL"
    rank = case.first_matching_rank if case.first_matching_rank is not None else "-"
    print(f"{status}\t{case.variable_name}\trank={rank}")
  return 0 if var_report.passed_count == var_report.sample_size else 1


__all__ = [
  "BenchmarkQuestion",
  "BenchmarkQuestionSuite",
  "BenchmarkReport",
  "PathEvaluationResult",
  "QuestionEvaluationResult",
  "VariableEvaluationCase",
  "VariableEvaluationConfig",
  "VariableEvaluationReport",
  "build_arg_parser",
  "evaluate_benchmark_suite",
  "evaluate_variable_retrieval",
  "generate_markdown_report",
  "main",
]
