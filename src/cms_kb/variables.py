"""Phase 6 variable-level metadata extraction from parsed CMS KB chunks."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from .parsing import ChunkMetadata

VariableFieldnames = Literal[
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
]
VariableEdgeFieldnames = Literal[
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "page",
  "chunk_id",
]

VARIABLE_FIELDNAMES: list[VariableFieldnames] = [
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
]
VARIABLE_EDGE_FIELDNAMES: list[VariableEdgeFieldnames] = [
  "source_id",
  "target_id",
  "relationship",
  "source_url",
  "source_document",
  "page",
  "chunk_id",
]

VARIABLE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:_[A-Z0-9]+)+\b")
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DEFINITION_SEPARATOR_PATTERN = re.compile(r"\s+(?:[-:–—]|=)\s+")
ALIAS_PATTERN = re.compile(
  r"\b(?:also known as|aka|alias(?:es)?|formerly)\b[:\s]+([^.;\n]+)",
  re.IGNORECASE,
)


class VariableExtractionConfig(BaseModel):
  chunks_jsonl_path: Path = Path("data/parsed/chunks.jsonl")
  metadata_dir: Path = Path("data/metadata")
  graph_dir: Path = Path("data/graph")
  workspace_dir: Path = Path("_workspace")


class VariableMetadataRow(BaseModel):
  variable_id: str
  variable_name: str
  dataset_id: str
  definition: str
  aliases: str = ""
  years: str = ""
  source_document: str
  source_url: str
  page: int | None = None
  chunk_id: str
  extraction_notes: str = ""


class VariableEdgeRow(BaseModel):
  source_id: str
  target_id: str
  relationship: str = "contains"
  source_url: str
  source_document: str
  page: int | None = None
  chunk_id: str


class VariableExtractionFailure(BaseModel):
  chunk_id: str = ""
  source_document: str = ""
  reason: str


class VariableExtractionResult(BaseModel):
  config: VariableExtractionConfig
  chunks_read: int = 0
  variables: list[VariableMetadataRow] = Field(default_factory=list)
  edges: list[VariableEdgeRow] = Field(default_factory=list)
  skipped_candidates: int = 0
  failures: list[VariableExtractionFailure] = Field(default_factory=list)

  @property
  def variable_count(self) -> int:
    return len(self.variables)

  @property
  def edge_count(self) -> int:
    return len(self.edges)

  @property
  def failure_count(self) -> int:
    return len(self.failures)


def _slugify(value: str) -> str:
  slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
  return slug or "unknown"


def _stable_variable_id(dataset_id: str, variable_name: str) -> str:
  return f"{_slugify(dataset_id)}__var__{_slugify(variable_name)}"


def _clean_definition(value: str) -> str:
  cleaned = re.sub(r"\s+", " ", value).strip(" .;:-–—")
  return cleaned


def _candidate_definition(line: str, variable_name: str) -> str | None:
  match = re.search(rf"\b{re.escape(variable_name)}\b", line)
  if match is None:
    return None

  after = line[match.end():].strip()
  if not after:
    return None

  separator_match = DEFINITION_SEPARATOR_PATTERN.match(f" {after}")
  if separator_match is not None:
    definition = after[separator_match.end() - 1:]
    return _clean_definition(definition)

  lower_after = after.lower()
  for prefix in ("means ", "indicates ", "identifies ", "is "):
    if lower_after.startswith(prefix):
      return _clean_definition(after[len(prefix):])

  return None


def _extract_aliases(line: str) -> str:
  aliases: set[str] = set()
  for match in ALIAS_PATTERN.finditer(line):
    for raw_alias in re.split(r",|\bor\b", match.group(1)):
      alias = raw_alias.strip(" .;()")
      if alias and YEAR_PATTERN.fullmatch(alias) is None:
        aliases.add(alias)
  return "|".join(sorted(aliases))


def _extract_years(line: str) -> str:
  return "|".join(sorted(set(YEAR_PATTERN.findall(line))))


def extract_variables_from_chunk(
  chunk: ChunkMetadata,
) -> tuple[list[VariableMetadataRow], int]:
  rows: list[VariableMetadataRow] = []
  skipped_candidates = 0
  seen_in_chunk: set[str] = set()

  for raw_line in chunk.text.splitlines():
    line = re.sub(r"\s+", " ", raw_line).strip()
    if not line:
      continue
    for variable_name in sorted(set(VARIABLE_PATTERN.findall(line))):
      if variable_name in seen_in_chunk:
        continue
      seen_in_chunk.add(variable_name)
      definition = _candidate_definition(line, variable_name)
      if definition is None:
        skipped_candidates += 1
        continue
      rows.append(
        VariableMetadataRow(
          variable_id=_stable_variable_id(chunk.dataset, variable_name),
          variable_name=variable_name,
          dataset_id=chunk.dataset,
          definition=definition,
          aliases=_extract_aliases(line),
          years=_extract_years(line),
          source_document=chunk.source_document,
          source_url=chunk.url,
          page=chunk.page,
          chunk_id=chunk.chunk_id,
        )
      )

  return rows, skipped_candidates


def read_chunks_jsonl(input_path: Path) -> tuple[list[ChunkMetadata], list[VariableExtractionFailure]]:
  chunks: list[ChunkMetadata] = []
  failures: list[VariableExtractionFailure] = []
  with input_path.open("r", encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, start=1):
      if not line.strip():
        continue
      try:
        payload = json.loads(line)
        chunks.append(ChunkMetadata.model_validate(payload))
      except Exception as exc:
        failures.append(
          VariableExtractionFailure(
            chunk_id=f"line-{line_number}",
            reason=f"failed to parse chunk JSON: {exc}",
          )
        )
  return chunks, failures


def _deduplicate_variables(
  rows: list[VariableMetadataRow],
) -> list[VariableMetadataRow]:
  unique: dict[str, VariableMetadataRow] = {}
  for row in rows:
    existing = unique.get(row.variable_id)
    if existing is None:
      unique[row.variable_id] = row
      continue
    if len(row.definition) > len(existing.definition):
      unique[row.variable_id] = row
  return sorted(unique.values(), key=lambda row: (row.dataset_id, row.variable_name))


def _edge_for_variable(row: VariableMetadataRow) -> VariableEdgeRow:
  return VariableEdgeRow(
    source_id=row.dataset_id,
    target_id=row.variable_id,
    source_url=row.source_url,
    source_document=row.source_document,
    page=row.page,
    chunk_id=row.chunk_id,
  )


def _write_model_csv[T: BaseModel](
  rows: list[T], output_path: Path, fieldnames: Sequence[str]
) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      writer.writerow(row.model_dump())


def write_variable_outputs(result: VariableExtractionResult) -> None:
  _write_model_csv(
    result.variables,
    result.config.metadata_dir / "variables.csv",
    VARIABLE_FIELDNAMES,
  )
  _write_model_csv(
    result.edges,
    result.config.graph_dir / "variable_edges.csv",
    VARIABLE_EDGE_FIELDNAMES,
  )


def write_variable_workspace_summary(result: VariableExtractionResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "07_variable_pack.md"
  lines = [
    "# Variable Pack",
    "",
    f"- Parsed chunks input: {result.config.chunks_jsonl_path}",
    f"- Chunks read: {result.chunks_read}",
    f"- Variables: {result.variable_count}",
    f"- Variable edges: {result.edge_count}",
    f"- Skipped candidates: {result.skipped_candidates}",
    f"- Failures: {result.failure_count}",
    "",
    "## Outputs",
    "",
    f"- Variable metadata: {result.config.metadata_dir / 'variables.csv'}",
    f"- Variable graph edges: {result.config.graph_dir / 'variable_edges.csv'}",
    "",
    "## Failures",
    "",
  ]
  if result.failures:
    lines.extend(["| chunk_id | source_document | reason |", "| --- | --- | --- |"])
    for failure in result.failures[:25]:
      reason_safe = failure.reason.replace("|", "\\|").replace("\n", " ")
      lines.append(
        f"| {failure.chunk_id} | {failure.source_document} | {reason_safe} |"
      )
    if len(result.failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(result.failures) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_variable_extraction(
  config: VariableExtractionConfig,
) -> tuple[VariableExtractionResult, Path]:
  chunks, failures = read_chunks_jsonl(config.chunks_jsonl_path)
  extracted_rows: list[VariableMetadataRow] = []
  skipped_candidates = 0

  for chunk in chunks:
    source_document = Path(chunk.source_document)
    if not chunk.source_document.strip():
      failures.append(
        VariableExtractionFailure(
          chunk_id=chunk.chunk_id,
          reason="chunk has empty source_document",
        )
      )
      continue
    if not source_document.is_file():
      failures.append(
        VariableExtractionFailure(
          chunk_id=chunk.chunk_id,
          source_document=chunk.source_document,
          reason="source_document does not exist locally",
        )
      )
      continue
    rows, skipped = extract_variables_from_chunk(chunk)
    extracted_rows.extend(rows)
    skipped_candidates += skipped

  variables = _deduplicate_variables(extracted_rows)
  result = VariableExtractionResult(
    config=config,
    chunks_read=len(chunks),
    variables=variables,
    edges=[_edge_for_variable(row) for row in variables],
    skipped_candidates=skipped_candidates,
    failures=failures,
  )
  write_variable_outputs(result)
  summary_path = write_variable_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Extract variable-level metadata from parsed CMS KB chunks."
  )
  parser.add_argument(
    "--chunks-jsonl",
    type=Path,
    default=Path("data/parsed/chunks.jsonl"),
  )
  parser.add_argument("--metadata-dir", type=Path, default=Path("data/metadata"))
  parser.add_argument("--graph-dir", type=Path, default=Path("data/graph"))
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = VariableExtractionConfig(
    chunks_jsonl_path=args.chunks_jsonl,
    metadata_dir=args.metadata_dir,
    graph_dir=args.graph_dir,
    workspace_dir=args.workspace_dir,
  )
  try:
    result, summary_path = run_variable_extraction(config)
    print(
      f"wrote {result.variable_count} variables and {result.edge_count} "
      f"variable edges; summary: {summary_path}"
    )
    return 1 if result.failure_count else 0
  except Exception as exc:
    print(f"Error executing variable extraction: {exc}", file=sys.stderr)
    return 1


__all__ = [
  "VARIABLE_EDGE_FIELDNAMES",
  "VARIABLE_FIELDNAMES",
  "VariableEdgeRow",
  "VariableExtractionConfig",
  "VariableExtractionFailure",
  "VariableExtractionResult",
  "VariableMetadataRow",
  "build_arg_parser",
  "extract_variables_from_chunk",
  "main",
  "read_chunks_jsonl",
  "run_variable_extraction",
  "write_variable_outputs",
  "write_variable_workspace_summary",
]
