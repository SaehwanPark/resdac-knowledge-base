from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest

from cms_kb.mcp import (
  get_agent_context,
  main,
  mcp,
  search_chunks,
  search_datasets,
  search_documents,
  search_variables,
  state,
)
from test_agent_api import _write_metadata_fixture


@pytest.fixture
def _setup_test_state(tmp_path: Path) -> Generator[None, None, None]:
  orig_config = state.config
  orig_limit = state.default_limit
  retrieval_config = _write_metadata_fixture(tmp_path)
  state.config = retrieval_config
  state.default_limit = 5
  yield
  state.config = orig_config
  state.default_limit = orig_limit


def test_mcp_tools_registration() -> None:
  registered_tools = [t.name for t in mcp._tool_manager.list_tools()]
  expected_tools = [
    "search_datasets",
    "search_documents",
    "search_variables",
    "search_chunks",
    "get_agent_context",
  ]
  for tool in expected_tools:
    assert tool in registered_tools


def test_search_datasets(_setup_test_state: None) -> None:
  # Search for the mbsf dataset
  response_str = search_datasets("mbsf")
  results = json.loads(response_str)
  assert len(results) == 1
  assert results[0]["record_id"] == "mbsf"
  assert results[0]["record_type"] == "dataset"
  assert results[0]["title"] == "Medicare Beneficiary Summary File"


def test_search_documents(_setup_test_state: None) -> None:
  # Search for the codebook document
  response_str = search_documents("codebook")
  results = json.loads(response_str)
  assert len(results) == 1
  assert results[0]["record_id"] == "mbsf__codebook"
  assert results[0]["record_type"] == "document"
  assert results[0]["title"] == "MBSF Codebook"


def test_search_variables(_setup_test_state: None) -> None:
  # Search for the BENE_ID variable
  response_str = search_variables("BENE_ID")
  results = json.loads(response_str)
  assert len(results) == 1
  assert results[0]["record_id"] == "mbsf__var__bene-id"
  assert results[0]["record_type"] == "variable"
  assert results[0]["title"] == "BENE_ID"


def test_search_chunks(_setup_test_state: None) -> None:
  # Search for chunk text
  response_str = search_chunks("Medicare")
  results = json.loads(response_str)
  assert len(results) == 1
  assert results[0]["record_id"] == "chunk-1"
  assert results[0]["record_type"] == "chunk"
  assert "Medicare" in results[0]["snippet"]


def test_get_agent_context(_setup_test_state: None) -> None:
  # Test the agent context search
  response_str = get_agent_context("BENE_ID")
  response = json.loads(response_str)
  assert response["query"] == "BENE_ID"
  assert len(response["results"]) == 1
  hit = response["results"][0]
  assert hit["record_id"] == "mbsf__var__bene-id"
  assert hit["record_type"] == "variable"
  assert hit["citation"]["source_url"] == "https://resdac.org/cms-data/files/mbsf-codebook"
  assert hit["citation"]["page"] == 3


def test_mcp_empty_query_raises(_setup_test_state: None) -> None:
  # Empty query should raise ValueError matching existing API behavior
  with pytest.raises(ValueError, match="query must not be empty"):
    search_datasets(" ")


def test_mcp_limit_fallback_and_override(_setup_test_state: None) -> None:
  # Verify tool uses state.default_limit when limit=None
  state.default_limit = 1
  response_str = search_variables("mbsf")
  results = json.loads(response_str)
  assert len(results) <= 1


def test_mcp_cli_fails_on_missing_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  # Main CLI should fail fast when paths do not exist
  exit_code = main([
    "--datasets-metadata",
    str(tmp_path / "missing_datasets.csv"),
    "--documents-metadata",
    str(tmp_path / "missing_documents.csv"),
  ])
  assert exit_code == 1
  captured = capsys.readouterr()
  assert "Datasets metadata file not found" in captured.err
