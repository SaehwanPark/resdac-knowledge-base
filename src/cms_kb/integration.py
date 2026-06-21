"""Downstream Integration APIs helper for the CMS Knowledge Base.

This module provides programmatic APIs and a CLI wrapper to perform year availability
checks on datasets and build schema crosswalks for variables across datasets.
"""

from __future__ import annotations

import argparse
import csv
import functools
import json
import re
import sys
from pydantic import BaseModel

from .paths import get_packaged_data_path


class DatasetAvailability(BaseModel):
  """Response model containing availability info for a dataset.

  Attributes:
    dataset_id: Unique identifier for the dataset.
    name: Human-readable name of the dataset.
    availability_raw: Unparsed availability string from datasets.csv metadata.
    available_years: Sorted list of years during which the dataset is available.
  """
  dataset_id: str
  name: str
  availability_raw: str
  available_years: list[int]


class VariableCrosswalkItem(BaseModel):
  """Crosswalk item mapping a variable name to a supporting dataset.

  Attributes:
    variable_name: Name of the variable.
    dataset_id: Identifier of the dataset containing this variable.
    dataset_name: Human-readable name of the dataset.
    definition: Excerpt/definition text for this variable in the dataset context.
    available_years: Sorted list of years during which the dataset is available.
    source_url: Source ResDAC or CCW documentation URL for this variable-dataset mapping.
  """
  variable_name: str
  dataset_id: str
  dataset_name: str
  definition: str
  available_years: list[int]
  source_url: str


class VariableCrosswalkResponse(BaseModel):
  """Structured response payload returned for crosswalking queries.

  Attributes:
    variables: A dictionary mapping queried variable names to lists of
      matching crosswalk items.
  """
  variables: dict[str, list[VariableCrosswalkItem]]


def parse_availability_years(availability_text: str) -> list[int]:
  """Extracts and expands year ranges and individual years from availability text.

  Args:
    availability_text: Raw availability description string.

  Returns:
    A sorted list of unique integer years extracted from the text.
  """
  if not availability_text:
    return []

  years: set[int] = set()

  # Find cohort ranges like "Cohort 18 (2015-2017) - Cohort 25 (2022-2024)"
  cohort_pattern = (
    r"Cohort\s+\d+\s*\((?P<start>\d{4})[^)]*\)\s*(?:-|to|through)\s*"
    r"Cohort\s+\d+\s*\([^)]*(?P<end>\d{4})\)"
  )
  cohort_match = re.search(cohort_pattern, availability_text, re.IGNORECASE)
  if cohort_match:
    start, end = int(cohort_match.group("start")), int(cohort_match.group("end"))
    if start <= end:
      years.update(range(start, end + 1))

  # Find ranges of format YYYY-YYYY or YYYY to YYYY (with potential letters/months in between)
  range_patterns = re.findall(
    r"(\d{4})\s*[^0-9\n]{0,25}?(?:-|to|through)\s*[^0-9\n]{0,25}?(\d{4})",
    availability_text,
    re.IGNORECASE,
  )
  for start_str, end_str in range_patterns:
    start, end = int(start_str), int(end_str)
    if start <= end:
      years.update(range(start, end + 1))

  # Find individual 4-digit years (using digit-boundary assertions to handle no spacing/concatenations)
  individual_years = re.findall(r"(?<!\d)\d{4}(?!\d)", availability_text)
  for year_str in individual_years:
    years.add(int(year_str))

  return sorted(list(years))


@functools.cache
def _load_datasets_map() -> dict[str, DatasetAvailability]:
  """Loads and caches dataset metadata into a map for fast lookup."""
  datasets_path = get_packaged_data_path("metadata/datasets.csv")
  if not datasets_path.is_file():
    return {}

  datasets_map: dict[str, DatasetAvailability] = {}
  with datasets_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      ds_id = row.get("dataset_id") or ""
      if ds_id:
        availability = row.get("availability") or ""
        datasets_map[ds_id] = DatasetAvailability(
          dataset_id=ds_id,
          name=row.get("name") or "",
          availability_raw=availability,
          available_years=parse_availability_years(availability),
        )
  return datasets_map


@functools.cache
def _load_variables_list() -> list[dict[str, str]]:
  """Loads and caches the variables CSV contents."""
  variables_path = get_packaged_data_path("metadata/variables.csv")
  if not variables_path.is_file():
    return []
  with variables_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    return [dict(row) for row in reader]


def get_dataset_availability(dataset_id: str) -> list[int]:
  """Retrieves the list of available years for a dataset by ID.

  Args:
    dataset_id: Dataset ID.

  Returns:
    Sorted list of years.

  Raises:
    ValueError: If datasets metadata is missing or the dataset is not found.
  """
  datasets_path = get_packaged_data_path("metadata/datasets.csv")
  if not datasets_path.is_file():
    raise ValueError(f"Metadata file {datasets_path} not found")

  datasets_map = _load_datasets_map()
  if dataset_id not in datasets_map:
    raise ValueError(f"Dataset {dataset_id} not found in metadata")

  return datasets_map[dataset_id].available_years


def check_dataset_availability(dataset_id: str, year: int) -> bool:
  """Checks if a dataset is available for a given year.

  Args:
    dataset_id: Dataset ID.
    year: The year to verify.

  Returns:
    True if the dataset is available in that year, False otherwise.
  """
  try:
    years = get_dataset_availability(dataset_id)
    return year in years
  except ValueError:
    return False


def crosswalk_variables(variable_names: list[str]) -> VariableCrosswalkResponse:
  """Finds all dataset occurrences of the specified variable names.

  Args:
    variable_names: Query variable names.

  Returns:
    A VariableCrosswalkResponse model.
  """
  datasets_map = _load_datasets_map()
  variables_rows = _load_variables_list()

  # Map each uppercase query to all original casing keys that matched it
  target_vars: dict[str, list[str]] = {}
  for var in variable_names:
    upper_var = var.upper()
    target_vars.setdefault(upper_var, []).append(var)

  result: dict[str, list[VariableCrosswalkItem]] = {
    var: [] for var in variable_names
  }

  for row in variables_rows:
    var_name = row.get("variable_name") or ""
    var_upper = var_name.upper()
    if var_upper in target_vars:
      for query_key in target_vars[var_upper]:
        ds_id = row.get("dataset_id") or ""
        if ds_id in datasets_map:
          ds_info = datasets_map[ds_id]
          ds_name = ds_info.name
          ds_years = ds_info.available_years
        else:
          ds_name = ds_id
          ds_years = []

        item = VariableCrosswalkItem(
          variable_name=var_name,
          dataset_id=ds_id,
          dataset_name=ds_name,
          definition=row.get("definition") or "",
          available_years=ds_years,
          source_url=row.get("source_url") or "",
        )
        result[query_key].append(item)

  return VariableCrosswalkResponse(variables=result)


def build_arg_parser() -> argparse.ArgumentParser:
  """Builds the ArgumentParser instance for integration subcommands."""
  parser = argparse.ArgumentParser(
    description="Downstream Integration APIs helper for the CMS Knowledge Base."
  )
  subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands")

  # Subcommand: availability
  availability_parser = subparsers.add_parser(
    "availability", help="Check availability of a dataset by ID and year."
  )
  availability_parser.add_argument(
    "--dataset", required=True, help="Dataset ID to check."
  )
  availability_parser.add_argument(
    "--year", type=int, help="Optional year to verify availability."
  )

  # Subcommand: crosswalk
  crosswalk_parser = subparsers.add_parser(
    "crosswalk",
    help="Retrieve schema crosswalk for variables across datasets.",
  )
  crosswalk_parser.add_argument(
    "--variables",
    required=True,
    help="Comma-separated list of variable names to crosswalk.",
  )

  return parser


def main(args: list[str] | None = None) -> int:
  """Main entry point for the integration CLI."""
  parser = build_arg_parser()
  parsed_args = parser.parse_args(args)

  try:
    if parsed_args.command == "availability":
      dataset_id = parsed_args.dataset
      year = parsed_args.year

      if year is not None:
        is_available = check_dataset_availability(dataset_id, year)
        print(json.dumps(is_available))
      else:
        # Use cached datasets map directly to retrieve raw string details
        datasets_map = _load_datasets_map()
        if dataset_id not in datasets_map:
          raise ValueError(f"Dataset {dataset_id} not found in metadata")
        resp = datasets_map[dataset_id]
        print(resp.model_dump_json(indent=2))

    elif parsed_args.command == "crosswalk":
      variables_list = [
        v.strip() for v in parsed_args.variables.split(",") if v.strip()
      ]
      response = crosswalk_variables(variables_list)
      print(response.model_dump_json(indent=2))

    return 0
  except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
  sys.exit(main())
