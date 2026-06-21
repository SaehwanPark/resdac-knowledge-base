import importlib.resources
from pathlib import Path

def get_packaged_data_path(subpath: str) -> Path:
  """Resolves the absolute path to a file packaged inside cms_kb/data, falling back to local data/."""
  try:
    traversable_path = importlib.resources.files("cms_kb").joinpath("data").joinpath(subpath)
    # Check if the resource exists within the package (using official Traversable interface)
    if traversable_path.is_file() or traversable_path.is_dir():
      return Path(str(traversable_path))
  except Exception:
    pass
  # Fallback to local data folder for development environment
  return Path("data") / subpath
