import json
import pytest
from cms_kb.integration import (
  parse_availability_years,
  get_dataset_availability,
  check_dataset_availability,
  crosswalk_variables,
  VariableCrosswalkResponse,
  main,
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
