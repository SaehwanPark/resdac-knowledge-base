# ResDAC/CMS Knowledge Base PyPI Publishing Guide

This guide outlines the steps required to prepare, optimize, validate, and publish the `resdac-knowledge-base` package to PyPI.

---

## 1. Release Checklist & Prerequisites

Before initiating a release, ensure all checks pass to maintain package integrity:

- [ ] **Branch**: Ensure you are on the `main` branch and synchronized with remote.
- [ ] **Tests & Lints**: Run the verification suite:
  ```bash
  # Run test suite
  uv run pytest

  # Check style (note: Ruff is configured in lint-only mode; do not run `ruff format`)
  uv run ruff check .

  # Run static type checking
  uv run basedpyright .

  # Run pipeline validation check
  uv run python scripts/validate_harness.py
  ```

---

## 2. Versioning & Changelog

1. **Update Version**: Open [pyproject.toml](file:///Users/saehwan/repos/resdac-knowledge-base/pyproject.toml) and update the `version` field under `[project]` following Semantic Versioning (SemVer):
   ```toml
   [project]
   name = "knowledge"
   version = "X.Y.Z"
   ```
2. **Lock Dependencies**: Sync the environment and update `uv.lock`:
   ```bash
   uv sync
   ```
3. **Document Changes**: Update [CHANGELOG.md](file:///Users/saehwan/repos/resdac-knowledge-base/CHANGELOG.md) by moving changes from `## Unreleased` to a new version header (e.g., `## [X.Y.Z] - YYYY-MM-DD`).

---

## 3. Asset Optimization & Build Verification

The package bundles pre-built knowledge base files (the serving database and parsed metadata) inside the wheel. To ensure we stay under the **100MB PyPI upload limit** and exclude raw PDF binaries, run the automated verification script:

```bash
uv run python scripts/build_check.py
```

### What this script does:
1. **Cleans Build Staging**: Removes the `dist/` directory to prevent stale artifacts.
2. **Optimizes Serving Assets**: Calls [scripts/optimize_assets.py](file:///Users/saehwan/repos/resdac-knowledge-base/scripts/optimize_assets.py) which:
   - VACUUMs and optimizes the SQLite index (`src/cms_kb/data/index/retrieval.sqlite`) using `PRAGMA optimize;` to minimize database file size.
   - Cleans raw HTML pages (`src/cms_kb/data/raw/html`) by stripping layouts, header/footer elements, styles, SVGs, scripts, and comments to reduce HTML footprint by 80-90%.
3. **Builds the Package**: Compiles the source distribution and wheel using `uv build`.
4. **Verifies Size and Contents**:
   - Asserts the `.whl` size is **< 100MB**.
   - Verifies the inclusion of `retrieval.sqlite`, `datasets.csv`, and `chunks.jsonl`.
   - Asserts that no raw `.pdf` files are included.

---

## 4. Executing PyPI Publishing

We use `uv publish` to upload package distributions. Always perform a dry run and TestPyPI verification first.

### Step A: TestPyPI Verification (Recommended)

1. **Dry-Run Upload**:
   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/ --dry-run
   ```
2. **Publish to TestPyPI**:
   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/ --token <TEST_PYPI_API_TOKEN>
   ```
3. **Install & Test**: Verify that the package installs correctly from TestPyPI:
   ```bash
   uv run pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ resdac-doc-archive
   ```

### Step B: Production PyPI Release

1. **Dry-Run Upload**:
   ```bash
   uv publish --dry-run
   ```
2. **Publish to PyPI**:
   ```bash
   uv publish --token <PYPI_API_TOKEN>
   ```
   > [!TIP]
   > You can define the environment variable `UV_PUBLISH_TOKEN` to automatically supply the API token.

---

## 5. Post-Publish Git Tagging

Once the package is successfully published to PyPI, tag the commit and push it to GitHub:

```bash
# Tag the release commit
git tag -a vX.Y.Z -m "Release vX.Y.Z"

# Push the tag to remote
git push origin vX.Y.Z
```
