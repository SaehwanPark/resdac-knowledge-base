"""Phase 1 archive preservation for CMS KB inventory outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from .inventory import (
  InventoryRow,
  ResourceKind,
  classify_asset_kind,
  read_inventory_csv,
)

ArchiveState = Literal["archived", "skipped", "failed"]

ARCHIVE_MANIFEST_FIELDNAMES = [
  "url",
  "resource_kind",
  "asset_kind",
  "source_url",
  "source_title",
  "content_type",
  "http_status",
  "archive_state",
  "downloaded_at_utc",
  "sha256",
  "local_path",
  "error",
]

HTML_RESOURCE_KINDS: tuple[ResourceKind, ...] = (
  "listing_page",
  "dataset_page",
  "documentation_page",
)


class ArchiveConfig(BaseModel):
  inventory_path: Path = Path("manifests/site_inventory.csv")
  raw_root: Path = Path("data/raw")
  manifest_output_path: Path = Path("manifests/archive_manifest.csv")
  workspace_dir: Path = Path("_workspace")
  timeout_seconds: float = 20.0
  request_delay_seconds: float = 0.0
  user_agent: str = "Mozilla/5.0 (compatible; cms-kb-archive/0.1)"


class ArchiveManifestRow(BaseModel):
  url: str
  resource_kind: ResourceKind
  asset_kind: str = ""
  source_url: str = ""
  source_title: str = ""
  content_type: str = ""
  http_status: int | None = None
  archive_state: ArchiveState
  downloaded_at_utc: str = ""
  sha256: str = ""
  local_path: str = ""
  error: str = ""


class DownloadResult(BaseModel):
  url: str
  status: int | None = None
  content_type: str | None = None
  body: bytes = b""
  error: str = ""


class ArchiveResult(BaseModel):
  config: ArchiveConfig
  inventory_rows: int
  manifest_rows: list[ArchiveManifestRow] = Field(default_factory=list)
  archived_count: int = 0
  skipped_count: int = 0
  failed_count: int = 0


def _request_bytes_with_retry(
  request: Request,
  *,
  timeout_seconds: float,
  retry_statuses: set[int],
) -> DownloadResult:
  delay_seconds = 1.0
  for attempt in range(3):
    try:
      with urlopen(request, timeout=timeout_seconds) as response:
        return DownloadResult(
          url=request.full_url,
          status=int(response.status),
          content_type=response.headers.get_content_type(),
          body=response.read(),
        )
    except HTTPError as exc:
      if exc.code in retry_statuses and attempt < 2:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        sleep_seconds = _parse_retry_after_seconds(retry_after) or delay_seconds
        _sleep(sleep_seconds)
        delay_seconds *= 2
        continue
      return DownloadResult(
        url=request.full_url,
        status=int(exc.code),
        content_type=exc.headers.get_content_type() if exc.headers else None,
        error=str(exc),
      )
    except URLError as exc:
      if attempt < 2:
        _sleep(delay_seconds)
        delay_seconds *= 2
        continue
      return DownloadResult(url=request.full_url, error=str(exc.reason))
  return DownloadResult(url=request.full_url, error="unknown download failure")


def _parse_retry_after_seconds(retry_after: str | None) -> float | None:
  if retry_after is None:
    return None
  if retry_after.isdigit():
    return float(retry_after)
  try:
    retry_at = parsedate_to_datetime(retry_after)
  except (TypeError, ValueError):
    return None
  if retry_at.tzinfo is None:
    retry_at = retry_at.replace(tzinfo=UTC)
  return max((retry_at - datetime.now(UTC)).total_seconds(), 0.0)


def _sleep(seconds: float) -> None:
  import time

  time.sleep(seconds)


def download_url(url: str, timeout_seconds: float, user_agent: str) -> DownloadResult:
  request = Request(url, headers={"User-Agent": user_agent}, method="GET")
  return _request_bytes_with_retry(
    request,
    timeout_seconds=timeout_seconds,
    retry_statuses={429, 500, 502, 503, 504},
  )


def _should_archive(row: InventoryRow) -> bool:
  if row.link_state != "live":
    return False
  if row.http_status is None or row.http_status >= 400:
    return False
  return row.resource_kind in HTML_RESOURCE_KINDS or row.resource_kind == "asset"


def _slug_for_row(row: InventoryRow) -> str:
  return hashlib.sha1(row.url.encode("utf-8")).hexdigest()


def _asset_extension(row: InventoryRow) -> str:
  path = urlparse(row.url).path.lower()
  suffix = Path(path).suffix
  if suffix:
    return suffix
  asset_kind = classify_asset_kind(row.url, row.content_type or None)
  return {
    "pdf": ".pdf",
    "xlsx": ".xlsx",
    "xls": ".xls",
    "csv": ".csv",
    "zip": ".zip",
  }.get(asset_kind, ".bin")


def archive_path_for_row(row: InventoryRow, raw_root: Path) -> Path:
  slug = _slug_for_row(row)
  if row.resource_kind in HTML_RESOURCE_KINDS:
    return raw_root / "html" / row.resource_kind / f"{slug}.html"
  asset_kind = row.asset_kind or classify_asset_kind(row.url, row.content_type or None)
  asset_dir = asset_kind or "other"
  return raw_root / "assets" / asset_dir / f"{slug}{_asset_extension(row)}"


def _manifest_row_for_skip(row: InventoryRow) -> ArchiveManifestRow:
  return ArchiveManifestRow(
    url=row.url,
    resource_kind=row.resource_kind,
    asset_kind=row.asset_kind,
    source_url=row.source_url,
    source_title=row.source_title,
    content_type=row.content_type,
    http_status=row.http_status,
    archive_state="skipped",
    error="inventory row is not a live archive target",
  )


def _manifest_row_for_failure(
  row: InventoryRow, download: DownloadResult, downloaded_at_utc: str
) -> ArchiveManifestRow:
  return ArchiveManifestRow(
    url=row.url,
    resource_kind=row.resource_kind,
    asset_kind=row.asset_kind,
    source_url=row.source_url,
    source_title=row.source_title,
    content_type=download.content_type or row.content_type,
    http_status=download.status,
    archive_state="failed",
    downloaded_at_utc=downloaded_at_utc,
    error=download.error or "download returned no body",
  )


def _manifest_row_for_success(
  row: InventoryRow,
  *,
  http_status: int | None,
  content_type: str,
  downloaded_at_utc: str,
  sha256: str,
  local_path: Path,
) -> ArchiveManifestRow:
  return ArchiveManifestRow(
    url=row.url,
    resource_kind=row.resource_kind,
    asset_kind=row.asset_kind,
    source_url=row.source_url,
    source_title=row.source_title,
    content_type=content_type,
    http_status=http_status,
    archive_state="archived",
    downloaded_at_utc=downloaded_at_utc,
    sha256=sha256,
    local_path=str(local_path),
  )


def write_archive_manifest(
  rows: list[ArchiveManifestRow], output_path: Path
) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=ARCHIVE_MANIFEST_FIELDNAMES)
    writer.writeheader()
    for row in rows:
      writer.writerow(row.model_dump())


def write_archive_workspace_summary(result: ArchiveResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "03_archive_manifest.md"
  lines = [
    "# Archive Manifest",
    "",
    f"- Inventory input: {result.config.inventory_path}",
    f"- Inventory rows: {result.inventory_rows}",
    f"- Archived: {result.archived_count}",
    f"- Skipped: {result.skipped_count}",
    f"- Failed: {result.failed_count}",
    "",
    "## Failures",
    "",
  ]
  failures = [row for row in result.manifest_rows if row.archive_state == "failed"]
  if failures:
    lines.extend(["| url | status | error |", "| --- | ---: | --- |"])
    for row in failures[:25]:
      lines.append(f"| {row.url} | {row.http_status or ''} | {row.error} |")
    if len(failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(failures) - 25}")
  else:
    lines.append("- None")
  lines.extend(["", "## Skipped", ""])
  skipped = [row for row in result.manifest_rows if row.archive_state == "skipped"]
  if skipped:
    lines.extend(["| url | state | reason |", "| --- | --- | --- |"])
    for row in skipped[:25]:
      lines.append(f"| {row.url} | {row.archive_state} | {row.error} |")
    if len(skipped) > 25:
      lines.append(f"\n- Additional skipped rows omitted: {len(skipped) - 25}")
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_archive(
  config: ArchiveConfig,
  *,
  read_inventory_fn: Callable[[Path], list[InventoryRow]] = read_inventory_csv,
  download_url_fn: Callable[[str, float, str], DownloadResult] = download_url,
  now_utc_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
  sleep_fn: Callable[[float], None] = _sleep,
) -> tuple[ArchiveResult, Path]:
  inventory_rows = read_inventory_fn(config.inventory_path)
  manifest_rows: list[ArchiveManifestRow] = []
  archived_count = 0
  skipped_count = 0
  failed_count = 0

  for row in inventory_rows:
    if not _should_archive(row):
      manifest_rows.append(_manifest_row_for_skip(row))
      skipped_count += 1
      continue

    if config.request_delay_seconds:
      sleep_fn(config.request_delay_seconds)
    download = download_url_fn(row.url, config.timeout_seconds, config.user_agent)
    downloaded_at_utc = now_utc_fn().isoformat().replace("+00:00", "Z")

    if download.status is None or download.status >= 400 or not download.body:
      manifest_rows.append(
        _manifest_row_for_failure(row, download, downloaded_at_utc)
      )
      failed_count += 1
      continue

    local_path = archive_path_for_row(row, config.raw_root)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(download.body)
    manifest_rows.append(
      _manifest_row_for_success(
        row,
        http_status=download.status,
        content_type=download.content_type or row.content_type,
        downloaded_at_utc=downloaded_at_utc,
        sha256=hashlib.sha256(download.body).hexdigest(),
        local_path=local_path,
      )
    )
    archived_count += 1

  result = ArchiveResult(
    config=config,
    inventory_rows=len(inventory_rows),
    manifest_rows=manifest_rows,
    archived_count=archived_count,
    skipped_count=skipped_count,
    failed_count=failed_count,
  )
  write_archive_manifest(manifest_rows, config.manifest_output_path)
  summary_path = write_archive_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Archive live CMS KB inventory targets into raw local storage."
  )
  parser.add_argument(
    "--inventory", type=Path, default=Path("manifests/site_inventory.csv")
  )
  parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
  parser.add_argument(
    "--manifest-output", type=Path, default=Path("manifests/archive_manifest.csv")
  )
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  parser.add_argument("--timeout-seconds", type=float, default=20.0)
  parser.add_argument("--request-delay-seconds", type=float, default=0.5)
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = ArchiveConfig(
    inventory_path=args.inventory,
    raw_root=args.raw_root,
    manifest_output_path=args.manifest_output,
    workspace_dir=args.workspace_dir,
    timeout_seconds=args.timeout_seconds,
    request_delay_seconds=args.request_delay_seconds,
  )
  result, summary_path = run_archive(config)
  print(
    f"wrote {len(result.manifest_rows)} archive rows to "
    f"{config.manifest_output_path} and {summary_path}"
  )
  return 1 if result.failed_count else 0


__all__ = [
  "ARCHIVE_MANIFEST_FIELDNAMES",
  "ArchiveConfig",
  "ArchiveManifestRow",
  "ArchiveResult",
  "DownloadResult",
  "archive_path_for_row",
  "build_arg_parser",
  "download_url",
  "main",
  "run_archive",
]
