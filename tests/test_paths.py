from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock
from cms_kb.paths import get_packaged_data_path

def test_get_packaged_data_path_local_fallback():
  # Verify fallback to local directory when resource does not exist or package not active
  path = get_packaged_data_path("metadata/does_not_exist.csv")
  assert path == Path("data/metadata/does_not_exist.csv")

def test_get_packaged_data_path_resource_exists():
  # Mock importlib.resources.files to verify it checks and returns the package resource
  mock_traversable: Any = MagicMock()
  mock_traversable.is_file.return_value = True
  mock_traversable.is_dir.return_value = False
  mock_traversable.__str__.return_value = "/mock/install/path/cms_kb/data/metadata/datasets.csv"
  
  mock_files: Any = MagicMock()
  mock_files.return_value.joinpath.return_value.joinpath.return_value = mock_traversable
  
  with patch("importlib.resources.files", mock_files):
    path = get_packaged_data_path("metadata/datasets.csv")
    assert path == Path("/mock/install/path/cms_kb/data/metadata/datasets.csv")
    mock_files.assert_called_once_with("cms_kb")
