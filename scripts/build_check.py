import shutil
import subprocess
import zipfile
from pathlib import Path
import optimize_assets

def run_build():
  repo_root = Path(__file__).resolve().parent.parent
  dist_dir = repo_root / "dist"
  
  # 1. Clean dist folder
  if dist_dir.exists():
    print(f"Cleaning dist folder: {dist_dir}")
    shutil.rmtree(dist_dir)
      
  # 2. Run optimize assets
  print("Running asset optimizer...")
  optimize_assets.main()
  
  # 3. Build package
  print("Building package with uv...")
  res = subprocess.run(["uv", "build"], cwd=str(repo_root), capture_output=True, text=True)
  if res.returncode != 0:
    print("Build failed!")
    print(res.stderr)
    return False
      
  print(res.stdout)
  
  # 4. Find generated wheel
  wheels = list(dist_dir.glob("*.whl"))
  if not wheels:
    print("No wheel file generated!")
    return False
      
  wheel_path = wheels[0]
  sz_mb = wheel_path.stat().st_size / 1024 / 1024
  print(f"Generated wheel: {wheel_path.name} (size: {sz_mb:.2f}MB)")
  
  # Check limit
  if sz_mb > 100.0:
    print("ERROR: Wheel size exceeds 100MB PyPI upload limit!")
    return False
  else:
    print("SUCCESS: Wheel size is under 100MB limit.")
      
  # 5. Verify wheel contents
  print("Verifying wheel contents...")
  has_db = False
  has_csv = False
  has_jsonl = False
  has_pdf = False
  
  with zipfile.ZipFile(wheel_path, "r") as zf:
    namelist = zf.namelist()
    for name in namelist:
      if "cms_kb/data/index/retrieval.sqlite" in name:
        has_db = True
      elif "cms_kb/data/metadata/datasets.csv" in name:
        has_csv = True
      elif "cms_kb/data/parsed/chunks.jsonl" in name:
        has_jsonl = True
      elif name.endswith(".pdf"):
        has_pdf = True
              
  if not has_db:
    print("ERROR: Wheel does not contain SQLite serving index!")
    return False
  if not has_csv:
    print("ERROR: Wheel does not contain metadata CSVs!")
    return False
  if not has_jsonl:
    print("ERROR: Wheel does not contain chunks JSONL!")
    return False
  if has_pdf:
    print("ERROR: Wheel mistakenly contains binary PDF assets!")
    return False
      
  print("SUCCESS: All verification checks passed successfully!")
  return True

if __name__ == "__main__":
  success = run_build()
  exit(0 if success else 1)
