from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np

# Mock sentence_transformers module before importing retrieval module
class MockSentenceTransformer:
  def __init__(self, model_name: str):
    self.model_name = model_name

  def encode(self, sentences, **kwargs):
    is_single = isinstance(sentences, str)
    if is_single:
      sentences = [sentences]
    
    embeddings = []
    for text in sentences:
      # Deterministic 384-dimensional vector based on string characters
      val = sum(ord(c) for c in text) % 100 / 100.0
      emb = np.zeros(384, dtype=np.float32)
      emb[0] = val
      emb[1] = 1.0 - val
      norm = np.linalg.norm(emb)
      if norm > 0:
        emb = emb / norm
      embeddings.append(emb)
      
    if is_single and kwargs.get("convert_to_numpy", True):
      return embeddings[0]
    return np.array(embeddings)

mock_sentence_transformers = MagicMock()
mock_sentence_transformers.SentenceTransformer = MockSentenceTransformer
sys.modules["sentence_transformers"] = mock_sentence_transformers

from cms_kb.retrieval import (  # noqa: E402
  build_index,
  run_retrieval,
)
from tests.test_retrieval import _write_metadata_fixture  # noqa: E402


def test_build_index_with_embeddings(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  
  # Build index with embeddings enabled
  build_index(config, build_embeddings=True)
  
  assert config.database_path.is_file()
  
  import sqlite3
  conn = sqlite3.connect(config.database_path)
  try:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert "record_embeddings" in tables
    
    cursor.execute("SELECT COUNT(*) FROM record_embeddings;")
    count = cursor.fetchone()[0]
    # We should have 4 records cached
    assert count == 4
    
    cursor.execute("SELECT record_id, embedding FROM record_embeddings LIMIT 1;")
    row = cursor.fetchone()
    assert row is not None
    rec_id, emb_bytes = row
    emb = np.frombuffer(emb_bytes, dtype=np.float32)
    assert len(emb) == 384
    # Check normalization
    assert np.allclose(np.linalg.norm(emb), 1.0)
  finally:
    conn.close()


def test_run_retrieval_hybrid(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  build_index(config, build_embeddings=True)
  
  # Enable hybrid search in config
  config.hybrid_search_enabled = True
  config.semantic_weight = 0.6
  
  results = run_retrieval(config, "dual eligibility", limit=5)
  
  # The chunk "Dual eligibility indicators describe Medicare and Medicaid enrollment."
  # should be retrieved and scored using the hybrid formula
  assert len(results) > 0
  assert results[0].record_type == "chunk"
  assert results[0].record_id == "chunk-1"
  assert "Dual eligibility" in results[0].snippet


def test_hybrid_fallback_when_table_missing(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  # Build standard index without embeddings table
  build_index(config, build_embeddings=False)
  
  config.hybrid_search_enabled = True
  
  # Should fallback to lexical search without throwing errors
  results = run_retrieval(config, "dual eligibility", limit=5)
  assert len(results) > 0
  assert results[0].record_id == "chunk-1"


def test_exact_identifier_boost_wins_in_hybrid(tmp_path: Path) -> None:
  config = _write_metadata_fixture(tmp_path)
  build_index(config, build_embeddings=True)
  
  config.hybrid_search_enabled = True
  config.semantic_weight = 0.8
  
  # Even with high semantic weight, exact match on variable_id/variable_name ("BENE_ID")
  # should rank the variable first because of the +8.0 boost.
  results = run_retrieval(config, "BENE_ID", limit=5)
  assert results[0].record_type == "variable"
  assert results[0].record_id == "mbsf__var__bene-id"
