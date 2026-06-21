import json
from pathlib import Path
import pytest
from cms_kb.integration import (
  parse_availability_years,
  get_dataset_availability,
  check_dataset_availability,
  crosswalk_variables,
  VariableCrosswalkResponse,
  generate_cohort_dictionary,
  CohortVariableDetail,
  main,
  format_agent_context,
  scan_codebase_caveats,
  CaveatScanResponse,
)


def test_parse_availability_years() -> None:
  # Simple range
  assert parse_availability_years("May 2018-April 2023") == [2018, 2019, 2020, 2021, 2022, 2023]
  
  # Multiple ranges
  assert parse_availability_years("Release 1: November 2020-March 2023Release 2: April 2023-September 2025") == [
    2020, 2021, 2022, 2023, 2024, 2025
  ]
  
  # Adjacent ranges without separators
  assert parse_availability_years("2015-20192021-2025") == [
    2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025
  ]
  
  # Mixed ranges and individual years
  assert parse_availability_years("Annual: 1999-2024Quarterly: 2024 Q1-Q4; 2025 Q1-Q3Monthly*: 2025 and 2026") == list(range(1999, 2027))
  
  # Concatenated years (without boundary chars)
  assert parse_availability_years("March 2023March 2024") == [2023, 2024]

  # Cohort ranges
  assert parse_availability_years("Cohort 18 (2015-2017) - Cohort 25 (2022-2024)") == list(range(2015, 2025))

  # Empty or invalid string
  assert parse_availability_years("") == []
  assert parse_availability_years("no years here") == []

def test_dataset_availability() -> None:
  # carrier-ffs is present in datasets.csv and has 1999-2024 (and 2025/2026 monthly)
  years = get_dataset_availability("carrier-ffs")
  assert 1999 in years
  assert 2024 in years
  assert 2026 in years
  assert 1998 not in years

  # check_dataset_availability wrapper
  assert check_dataset_availability("carrier-ffs", 2020) is True
  assert check_dataset_availability("carrier-ffs", 1990) is False

  # Invalid dataset raises ValueError
  with pytest.raises(ValueError, match="Dataset non-existent not found"):
    get_dataset_availability("non-existent")

def test_crosswalk_variables() -> None:
  # Query crosswalk for BENE_ID, which is in carrier-ffs, carrier-encounter, etc.
  response = crosswalk_variables(["BENE_ID"])
  assert isinstance(response, VariableCrosswalkResponse)
  assert "BENE_ID" in response.variables
  
  items = response.variables["BENE_ID"]
  assert len(items) > 0
  
  # Check fields of VariableCrosswalkItem
  item = items[0]
  assert item.variable_name == "BENE_ID"
  assert item.dataset_id != ""
  assert item.dataset_name != ""
  assert len(item.available_years) > 0
  assert item.source_url.startswith("http")

  # Case-insensitive duplicate query keys
  duplicate_response = crosswalk_variables(["bene_id", "BENE_ID"])
  assert "bene_id" in duplicate_response.variables
  assert "BENE_ID" in duplicate_response.variables
  assert len(duplicate_response.variables["bene_id"]) == len(duplicate_response.variables["BENE_ID"])
  assert len(duplicate_response.variables["BENE_ID"]) > 0

  # Non-existent variable returns empty list
  empty_response = crosswalk_variables(["NON_EXISTENT_VAR_ABC"])
  assert "NON_EXISTENT_VAR_ABC" in empty_response.variables
  assert empty_response.variables["NON_EXISTENT_VAR_ABC"] == []

def test_cli_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
  # Test availability CLI subcommand
  assert main(["availability", "--dataset", "carrier-ffs"]) == 0
  captured = capsys.readouterr()
  data = json.loads(captured.out)
  assert data["dataset_id"] == "carrier-ffs"
  assert data["name"] == "Original Medicare (Fee-for-Service) Carrier"
  assert 2020 in data["available_years"]

  # Test availability CLI subcommand with year parameter
  assert main(["availability", "--dataset", "carrier-ffs", "--year", "2020"]) == 0
  captured = capsys.readouterr()
  assert captured.out.strip() == "true"

  assert main(["availability", "--dataset", "carrier-ffs", "--year", "1990"]) == 0
  captured = capsys.readouterr()
  assert captured.out.strip() == "false"

  # Test availability CLI with non-existent dataset
  assert main(["availability", "--dataset", "non-existent"]) == 1
  captured = capsys.readouterr()
  assert "Error: Dataset non-existent not found" in captured.err

  # Test crosswalk CLI subcommand
  assert main(["crosswalk", "--variables", "BENE_ID, bene_id"]) == 0
  captured = capsys.readouterr()
  data = json.loads(captured.out)
  assert "BENE_ID" in data["variables"]
  assert "bene_id" in data["variables"]
  assert len(data["variables"]["BENE_ID"]) > 0


def test_generate_cohort_dictionary() -> None:
  # Query cohort dictionary for BENE_ID and bene_birth_dt
  result = generate_cohort_dictionary(["BENE_ID", "bene_birth_dt", "NON_EXISTENT_VAR"])
  assert isinstance(result, dict)
  assert "BENE_ID" in result
  assert "bene_birth_dt" in result
  assert "NON_EXISTENT_VAR" in result

  # Check BENE_ID detail
  bene_items = result["BENE_ID"]
  assert len(bene_items) > 0
  for item in bene_items:
    assert isinstance(item, CohortVariableDetail)
    assert item.variable_name == "BENE_ID"
    assert item.record_id != ""
    assert item.dataset_id != ""
    assert item.dataset_name != ""
    assert isinstance(item.available_years, list)
    assert item.source_url.startswith("http")
    # Verify prefix was stripped from definition
    assert not item.definition.startswith(f"{item.record_id} {item.variable_name} {item.dataset_id}")

  # Check that at least some matching datasets have populated availability years
  assert any(len(item.available_years) > 0 for item in bene_items)


  # Check bene_birth_dt detail
  birth_items = result["bene_birth_dt"]
  assert len(birth_items) > 0
  for item in birth_items:
    assert isinstance(item, CohortVariableDetail)
    # Check casing is preserved per-query key
    assert item.variable_name == "bene_birth_dt"

  # Check non-existent variable maps to empty list
  assert result["NON_EXISTENT_VAR"] == []


def test_cli_cohort_dictionary(capsys: pytest.CaptureFixture[str]) -> None:
  assert main(["cohort-dictionary", "--variables", "BENE_ID, bene_birth_dt"]) == 0
  captured = capsys.readouterr()
  data = json.loads(captured.out)
  assert "BENE_ID" in data
  assert "bene_birth_dt" in data
  assert len(data["BENE_ID"]) > 0
  # Ensure the serialized JSON fields are correct
  item = data["BENE_ID"][0]
  assert "variable_name" in item
  assert "record_id" in item
  assert "definition" in item
  assert "available_years" in item


def test_generate_cohort_dictionary_empty() -> None:
  # Verify that querying with empty list returns empty dict without errors
  assert generate_cohort_dictionary([]) == {}


def test_generate_cohort_dictionary_large_input() -> None:
  # Generate a large query list of 1000 variables to test SQLite parameter chunking limit
  query_list = [f"VAR_{i}" for i in range(1000)] + ["BENE_ID"]
  result = generate_cohort_dictionary(query_list)
  assert isinstance(result, dict)
  assert "BENE_ID" in result
  assert len(result["BENE_ID"]) > 0
  assert result["VAR_0"] == []


def test_format_agent_context() -> None:
  from cms_kb.agent_api import AgentContextResponse, AgentContextHit, AgentCitation
  response = AgentContextResponse(
    query="BENE_ID",
    results=[
      AgentContextHit(
        record_id="carrier-ffs-bene_id",
        record_type="variable",
        title="BENE_ID",
        dataset_id="carrier-ffs",
        score=1.5,
        snippet="This is a snippet for BENE_ID.",
        citation=AgentCitation(
          source_url="https://resdac.org/cms-data/variables/bene-id",
          source_document="data/raw/html/variable_page/bene_id.html"
        )
      )
    ]
  )

  # Format as prompt
  prompt_out = format_agent_context(response, "prompt")
  assert "=== CMS DOCUMENTATION CONTEXT ===" in prompt_out
  assert "Record: BENE_ID (variable)" in prompt_out
  assert "Snippet: This is a snippet for BENE_ID." in prompt_out
  assert "Source URL: https://resdac.org/cms-data/variables/bene-id" in prompt_out

  # Format as markdown
  markdown_out = format_agent_context(response, "markdown")
  assert "### CMS Documentation Context" in markdown_out
  assert "#### 1. BENE_ID (variable)" in markdown_out
  assert "**Source URL**:" in markdown_out

  # Format as xml
  xml_out = format_agent_context(response, "xml")
  assert "<documentation_context>" in xml_out
  assert '<record id="carrier-ffs-bene_id"' in xml_out
  assert "<excerpt>This is a snippet for BENE_ID.</excerpt>" in xml_out


def test_scan_codebase_caveats(tmp_path: Path) -> None:
  # Create a mock code file referencing BENE_ID and mbsf-base
  mock_script = tmp_path / "analysis.sas"
  mock_script.write_text("data cohort; set lib.carrier; run; * check BENE_ID and mbsf-base here;", encoding="utf-8")

  # Run scanner. BENE_ID matches variable metadata, mbsf-base matches dataset metadata
  response = scan_codebase_caveats([mock_script])
  assert isinstance(response, CaveatScanResponse)
  assert "BENE_ID" in response.matches
  assert "mbsf-base" in response.matches

  # Pass additional keywords
  response_with_kw = scan_codebase_caveats([mock_script], additional_keywords=["encounter"])
  assert "encounter" in response_with_kw.matches


def test_cli_integration_new_commands(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
  # Test scan-caveats CLI
  mock_script = tmp_path / "script.py"
  mock_script.write_text("import pandas\nprint(pandas.read_csv('mbsf-base'))\n# BENE_ID, GNDR_CD\n", encoding="utf-8")

  assert main(["scan-caveats", "--files", str(mock_script), "--keywords", "encounter"]) == 0
  captured = capsys.readouterr()
  data = json.loads(captured.out)
  assert "matches" in data
  assert "BENE_ID" in data["matches"]
  assert "mbsf-base" in data["matches"]
  assert "encounter" in data["matches"]


  # Test format-context CLI
  assert main(["format-context", "--query", "BENE_ID", "--format", "markdown", "--limit", "2"]) == 0
  captured = capsys.readouterr()
  assert "### CMS Documentation Context" in captured.out




