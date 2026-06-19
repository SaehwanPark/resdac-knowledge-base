"""Phase 1 archive preservation for CMS KB inventory outputs.

This module implements Phase 1 (Archive Preservation) of the CMS Knowledge Base pipeline.
It consumes the discovered site inventory, downloads HTML pages and asset attachments
from ResDAC/CMS, and persists them locally under `data/raw/` in a repeatable, traceable way.

Key Architecture Details:
- Robust Network Client: Implements auto-retry with exponential backoff, handling of transient
  HTTP codes, and parsing of standard 'Retry-After' response headers to respect rate limits.
- Rate Limit & Deferral: Deferrals are triggered for variable pages (which are numerous)
  if rate limits are repeatedly encountered. Remaining variable pages get deferred to protect
  general dataset/document crawls.
- Safe Writing: Uses atomic file writes (`_write_bytes_atomically`) by writing to a temporary file
  on the same filesystem and renaming it, preventing corrupt files if the process is terminated.
- Reuse & Validation: Performs trust checks on previous runs. Reuses existing files if their size
  and SHA-256 checksums match the recorded metadata, avoiding redundant network requests.
- Provenance Manifests: Registers the state of every download in `archive_manifest.csv` with its
  UTC download timestamp, checksum, content-type, and HTTP response code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import os
import random
import socket
import sys
import tempfile
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, model_validator

from .inventory import (
  InventoryRow,
  ResourceKind,
  classify_asset_kind,
  read_inventory_csv,
)
from .progress import append_progress_event, init_progress_log

ArchiveState = Literal["archived", "skipped", "failed", "deferred"]

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
  "variable_page",
)
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_RETRY_SLEEP_SECONDS = 300.0
VARIABLE_PAGE_BATCH_WARNING_THRESHOLD = 100
DEFERRED_AFTER_RATE_LIMITS_ERROR = "deferred after repeated HTTP 429 rate limits"


class ArchiveConfig(BaseModel):
  inventory_path: Path = Path("manifests/site_inventory.csv")
  raw_root: Path = Path("data/raw")
  manifest_output_path: Path = Path("manifests/archive_manifest.csv")
  workspace_dir: Path = Path("_workspace")
  timeout_seconds: float = 20.0
  request_delay_seconds: float = 0.0
  max_consecutive_rate_limits: int = 5
  retry_failed_only: bool = False
  max_downloads: int | None = None
  rate_limit_cooldown_seconds: float = 0.0
  progress_log_path: Path | None = None
  progress_interval: int = 25
  user_agent: str = "Mozilla/5.0 (compatible; cms-kb-archive/0.1)"

  @model_validator(mode="after")
  def validate_archive_controls(self) -> ArchiveConfig:
    if self.timeout_seconds <= 0:
      raise ValueError("timeout_seconds must be greater than 0")
    if self.request_delay_seconds < 0:
      raise ValueError("request_delay_seconds must be greater than or equal to 0")
    if self.max_consecutive_rate_limits < 1:
      raise ValueError("max_consecutive_rate_limits must be greater than 0")
    if self.max_downloads is not None and self.max_downloads < 0:
      raise ValueError("max_downloads must be greater than or equal to 0")
    if self.rate_limit_cooldown_seconds < 0:
      raise ValueError(
        "rate_limit_cooldown_seconds must be greater than or equal to 0"
      )
    if self.progress_interval < 0:
      raise ValueError("progress_interval must be greater than or equal to 0")
    return self


class ArchiveManifestRow(BaseModel):
  """A structured registry entry in the archive manifest.

  Tracks provenance and download outcomes for a single URL crawled in Phase 0.
  """
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

  @model_validator(mode="after")
  def validate_archived_provenance(self) -> ArchiveManifestRow:
    """Enforces integrity constraints on successfully archived entries."""
    if self.archive_state != "archived":
      return self
    if not self.downloaded_at_utc:
      raise ValueError("archived rows require downloaded_at_utc")
    try:
      datetime.fromisoformat(self.downloaded_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
      raise ValueError("archived rows require a valid downloaded_at_utc") from exc
    if not self.local_path:
      raise ValueError("archived rows require local_path")
    if len(self.sha256) != 64 or any(
      character not in "0123456789abcdefABCDEF" for character in self.sha256
    ):
      raise ValueError("archived rows require a 64-character hex sha256")
    return self


class DownloadResult(BaseModel):
  """Internal result containing raw network download outcomes."""
  url: str
  status: int | None = None
  content_type: str | None = None
  body: bytes = b""
  error: str = ""


class ArchiveResult(BaseModel):
  """Complete statistical summary for an archiving run."""
  config: ArchiveConfig
  inventory_rows: int
  manifest_rows: list[ArchiveManifestRow] = Field(default_factory=list)
  archived_count: int = 0
  skipped_count: int = 0
  failed_count: int = 0
  deferred_count: int = 0


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
        body = bytearray()
        while True:
          chunk = response.read(1024 * 1024)
          if not chunk:
            break
          body.extend(chunk)
          if len(body) > MAX_DOWNLOAD_BYTES:
            return DownloadResult(
              url=request.full_url,
              status=int(response.status),
              content_type=response.headers.get_content_type(),
              error=f"download exceeds maximum size of {MAX_DOWNLOAD_BYTES} bytes",
            )
        return DownloadResult(
          url=request.full_url,
          status=int(response.status),
          content_type=response.headers.get_content_type(),
          body=bytes(body),
        )
    except HTTPError as exc:
      if exc.code in retry_statuses and attempt < 2:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        sleep_seconds = min(
          _parse_retry_after_seconds(retry_after)
          or (delay_seconds + random.uniform(0, delay_seconds / 4)),
          MAX_RETRY_SLEEP_SECONDS,
        )
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
  if row.resource_kind == "variable_page":
    return row.link_state != "dead" and (
      row.http_status is None or row.http_status < 400
    )
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


def _manifest_row_for_not_attempted(row: InventoryRow, error: str) -> ArchiveManifestRow:
  return ArchiveManifestRow(
    url=row.url,
    resource_kind=row.resource_kind,
    asset_kind=row.asset_kind,
    source_url=row.source_url,
    source_title=row.source_title,
    content_type=row.content_type,
    http_status=row.http_status,
    archive_state="skipped",
    error=error,
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


def _download_failure(
  row: InventoryRow, error: str, downloaded_at_utc: str
) -> ArchiveManifestRow:
  return _manifest_row_for_failure(
    row,
    DownloadResult(
      url=row.url,
      status=row.http_status,
      content_type=row.content_type or None,
      error=error,
    ),
    downloaded_at_utc,
  )


def _manifest_row_for_deferred(
  row: InventoryRow, downloaded_at_utc: str
) -> ArchiveManifestRow:
  return ArchiveManifestRow(
    url=row.url,
    resource_kind=row.resource_kind,
    asset_kind=row.asset_kind,
    source_url=row.source_url,
    source_title=row.source_title,
    content_type=row.content_type,
    http_status=row.http_status,
    archive_state="deferred",
    downloaded_at_utc=downloaded_at_utc,
    error=DEFERRED_AFTER_RATE_LIMITS_ERROR,
  )


def _is_retriable_archive_state(state: ArchiveState) -> bool:
  return state in {"failed", "deferred"}


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


def _host_is_private_or_local(hostname: str) -> bool:
  try:
    addresses = [ipaddress.ip_address(hostname)]
  except ValueError:
    try:
      resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
      return False
    addresses = [
      ipaddress.ip_address(result[4][0])
      for result in resolved
      if result[4] and result[4][0]
    ]

  return any(
    address.is_private
    or address.is_loopback
    or address.is_link_local
    or address.is_multicast
    or address.is_reserved
    or address.is_unspecified
    for address in addresses
  )


def _archive_url_error(url: str) -> str:
  parsed = urlparse(url)
  if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    return "archive URL must be an absolute http(s) URL"
  if parsed.hostname.lower() == "localhost":
    return "archive URL host resolves to a private or local address"
  if _host_is_private_or_local(parsed.hostname):
    return "archive URL host resolves to a private or local address"
  return ""


def _write_bytes_atomically(local_path: Path, body: bytes) -> str:
  """Writes data to a temporary file first, then renames it to prevent half-written files.

  This is a safety-critical design pattern to protect raw archive artifacts against
  system crashes or manual script interruptions.

  Args:
    local_path: The target path where the file should be permanently saved.
    body: The raw bytes data to be written.

  Returns:
    The computed 64-character hex SHA-256 checksum of the written bytes.
  """
  local_path.parent.mkdir(parents=True, exist_ok=True)
  hasher = hashlib.sha256()
  with tempfile.NamedTemporaryFile(
    mode="wb",
    dir=local_path.parent,
    prefix=f".{local_path.name}.",
    delete=False,
  ) as handle:
    temp_path = Path(handle.name)
    hasher.update(body)
    handle.write(body)
  try:
    os.replace(temp_path, local_path)
  except Exception:
    temp_path.unlink(missing_ok=True)
    raise
  return hasher.hexdigest()


def _read_trusted_previous_manifest(
  manifest_path: Path,
) -> dict[tuple[str, str], str]:
  if not manifest_path.is_file():
    return {}

  trusted: dict[tuple[str, str], str] = {}
  with manifest_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
      if row.get("archive_state") != "archived":
        continue
      url = (row.get("url") or "").strip()
      local_path = (row.get("local_path") or "").strip()
      sha256 = (row.get("sha256") or "").strip()
      if url and local_path and sha256:
        trusted[(url, local_path)] = sha256
  return trusted


def _read_previous_manifest_rows(
  manifest_path: Path,
) -> dict[str, ArchiveManifestRow]:
  if not manifest_path.is_file():
    return {}

  rows: dict[str, ArchiveManifestRow] = {}
  with manifest_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    missing_columns = set(ARCHIVE_MANIFEST_FIELDNAMES) - set(reader.fieldnames or [])
    if missing_columns:
      missing = ", ".join(sorted(missing_columns))
      raise ValueError(f"{manifest_path} missing required columns: {missing}")
    for row in reader:
      url = (row.get("url") or "").strip()
      if not url:
        continue
      status_text = (row.get("http_status") or "").strip()
      normalized = {field: row.get(field) or "" for field in ARCHIVE_MANIFEST_FIELDNAMES}
      normalized["url"] = url
      normalized["http_status"] = int(status_text) if status_text else None
      rows[url] = ArchiveManifestRow.model_validate(normalized)
  return rows


def _existing_file_is_trusted(
  row: InventoryRow,
  local_path: Path,
  previous_manifest: dict[tuple[str, str], str],
) -> bool:
  expected_sha256 = previous_manifest.get((row.url, str(local_path)))
  if expected_sha256 is None:
    return False
  body = local_path.read_bytes()
  return hashlib.sha256(body).hexdigest() == expected_sha256


def _manifest_row_for_existing_file(
  row: InventoryRow,
  *,
  downloaded_at_utc: str,
  local_path: Path,
) -> ArchiveManifestRow:
  body = local_path.read_bytes()
  return _manifest_row_for_success(
    row,
    http_status=row.http_status,
    content_type=row.content_type,
    downloaded_at_utc=downloaded_at_utc,
    sha256=hashlib.sha256(body).hexdigest(),
    local_path=local_path,
  )


def _previous_archive_row_is_trusted(row: ArchiveManifestRow) -> bool:
  if row.archive_state != "archived" or not row.local_path or not row.sha256:
    return False
  local_path = Path(row.local_path)
  if not local_path.is_file() or local_path.stat().st_size <= 0:
    return False
  return hashlib.sha256(local_path.read_bytes()).hexdigest() == row.sha256


def _increment_counts(
  row: ArchiveManifestRow,
  *,
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
) -> tuple[int, int, int, int]:
  if row.archive_state == "archived":
    archived_count += 1
  elif row.archive_state == "skipped":
    skipped_count += 1
  elif row.archive_state == "deferred":
    deferred_count += 1
  else:
    failed_count += 1
  return archived_count, skipped_count, failed_count, deferred_count


def _count_map(
  *,
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
) -> dict[str, int]:
  counts = {
    "archived": archived_count,
    "skipped": skipped_count,
    "failed": failed_count,
    "deferred": deferred_count,
  }
  return counts


def _archive_progress_counts(
  *,
  rows_processed: int,
  inventory_rows: int,
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
  download_attempts: int,
  consecutive_rate_limits: int,
  circuit_breaker_open: bool = False,
) -> dict[str, int]:
  counts = {
    "rows_processed": rows_processed,
    "inventory_rows": inventory_rows,
    "archived": archived_count,
    "skipped": skipped_count,
    "failed": failed_count,
    "deferred": deferred_count,
    "download_attempts": download_attempts,
  }
  if consecutive_rate_limits:
    counts["consecutive_rate_limits"] = consecutive_rate_limits
  if circuit_breaker_open:
    counts["circuit_breaker_open"] = 1
  return counts


def _emit_archive_periodic_progress(
  config: ArchiveConfig,
  progress_fn: Callable[[str], None] | None,
  *,
  rows_processed: int,
  inventory_rows: int,
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
  download_attempts: int,
  consecutive_rate_limits: int,
  circuit_breaker_open: bool = False,
  force: bool = False,
) -> None:
  if config.progress_interval == 0:
    return
  if not force and rows_processed % config.progress_interval != 0:
    return
  counts = _archive_progress_counts(
    rows_processed=rows_processed,
    inventory_rows=inventory_rows,
    archived_count=archived_count,
    skipped_count=skipped_count,
    failed_count=failed_count,
    deferred_count=deferred_count,
    download_attempts=download_attempts,
    consecutive_rate_limits=consecutive_rate_limits,
    circuit_breaker_open=circuit_breaker_open,
  )
  if progress_fn is not None:
    deferred_suffix = f" deferred={deferred_count}" if deferred_count else ""
    rate_suffix = (
      f" consecutive_rate_limits={consecutive_rate_limits}"
      if consecutive_rate_limits
      else ""
    )
    breaker_suffix = " circuit_breaker=open" if circuit_breaker_open else ""
    progress_fn(
      "progress: "
      f"{rows_processed}/{inventory_rows} rows "
      f"(archived={archived_count} skipped={skipped_count} failed={failed_count}"
      f"{deferred_suffix} download_attempts={download_attempts}{rate_suffix}"
      f"{breaker_suffix})"
    )
  append_progress_event(
    config.progress_log_path,
    phase="archive",
    event="progress",
    counts=counts,
  )


def _advance_archive_row_progress(
  config: ArchiveConfig,
  progress_fn: Callable[[str], None] | None,
  *,
  rows_processed: int,
  inventory_rows: int,
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
  download_attempts: int,
  consecutive_rate_limits: int,
  circuit_breaker_open: bool = False,
) -> int:
  rows_processed += 1
  _emit_archive_periodic_progress(
    config,
    progress_fn,
    rows_processed=rows_processed,
    inventory_rows=inventory_rows,
    archived_count=archived_count,
    skipped_count=skipped_count,
    failed_count=failed_count,
    deferred_count=deferred_count,
    download_attempts=download_attempts,
    consecutive_rate_limits=consecutive_rate_limits,
    circuit_breaker_open=circuit_breaker_open,
  )
  return rows_processed


def _archive_order_key(row: InventoryRow) -> tuple[int, str]:
  if row.resource_kind == "variable_page" and "encrypted-ccw-beneficiary-id" in row.url:
    return (0, row.url)
  if row.resource_kind != "variable_page":
    return (1, row.url)
  return (2, row.url)


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
    f"- Deferred: {result.deferred_count}",
    "",
  ]
  failures = [row for row in result.manifest_rows if row.archive_state == "failed"]
  deferred = [row for row in result.manifest_rows if row.archive_state == "deferred"]
  if failures or deferred:
    rate_limited_failures = [
      row
      for row in failures
      if row.http_status == 429 or "rate limit" in row.error.lower()
    ]
    if rate_limited_failures or deferred:
      lines.extend([
        "## Retry Guidance",
        "",
        (
          "Rate-limited or deferred variable-page rows are present. Retry later in "
          "bounded batches with "
          "`uv run cms-kb-archive --retry-failed-only --max-downloads 50 "
          "--request-delay-seconds 5 --rate-limit-cooldown-seconds 300`."
        ),
        "",
      ])
  lines.extend(["## Failures", ""])
  if failures:
    lines.extend(["| url | status | error |", "| --- | ---: | --- |"])
    for row in failures[:25]:
      lines.append(f"| {row.url} | {row.http_status or ''} | {row.error} |")
    if len(failures) > 25:
      lines.append(f"\n- Additional failures omitted: {len(failures) - 25}")
  else:
    lines.append("- None")
  lines.extend(["", "## Deferred", ""])
  if deferred:
    lines.extend(["| url | error |", "| --- | --- |"])
    for row in deferred[:25]:
      lines.append(f"| {row.url} | {row.error} |")
    if len(deferred) > 25:
      lines.append(f"\n- Additional deferred rows omitted: {len(deferred) - 25}")
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


def _bulk_defer_remaining_rows(
  config: ArchiveConfig,
  progress_fn: Callable[[str], None] | None,
  *,
  sorted_rows: list[InventoryRow],
  start_index: int,
  manifest_rows: list[ArchiveManifestRow],
  archived_count: int,
  skipped_count: int,
  failed_count: int,
  deferred_count: int,
  rows_processed: int,
  inventory_row_count: int,
  download_attempts: int,
  consecutive_rate_limits: int,
  now_utc_fn: Callable[[], datetime],
  previous_manifest_rows: dict[str, ArchiveManifestRow],
) -> tuple[int, int, int, int, int]:
  bulk_deferred = 0
  downloaded_at_utc = now_utc_fn().isoformat().replace("+00:00", "Z")
  for row in sorted_rows[start_index:]:
    previous_row = previous_manifest_rows.get(row.url)
    if not _should_archive(row):
      manifest_row = _manifest_row_for_skip(row)
    elif (
      config.retry_failed_only
      and previous_row is not None
      and not _is_retriable_archive_state(previous_row.archive_state)
    ):
      if previous_row.archive_state == "archived" and not _previous_archive_row_is_trusted(
        previous_row
      ):
        manifest_row = _download_failure(
          row,
          "previous archived row is missing or checksum does not match",
          downloaded_at_utc,
        )
      else:
        manifest_row = previous_row
    else:
      manifest_row = _manifest_row_for_deferred(row, downloaded_at_utc)
      bulk_deferred += 1
    manifest_rows.append(manifest_row)
    archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
      manifest_row,
      archived_count=archived_count,
      skipped_count=skipped_count,
      failed_count=failed_count,
      deferred_count=deferred_count,
    )
    rows_processed += 1
    if (
      config.progress_interval > 0
      and rows_processed % config.progress_interval == 0
    ):
      _emit_archive_periodic_progress(
        config,
        progress_fn,
        rows_processed=rows_processed,
        inventory_rows=inventory_row_count,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
        download_attempts=download_attempts,
        consecutive_rate_limits=consecutive_rate_limits,
        circuit_breaker_open=True,
        force=True,
      )

  if bulk_deferred:
    append_progress_event(
      config.progress_log_path,
      phase="archive",
      event="circuit_breaker_bulk",
      message=(
        f"deferred {bulk_deferred} remaining variable pages after repeated HTTP 429 "
        "rate limits"
      ),
      counts=_count_map(
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      | {
        "consecutive_rate_limits": consecutive_rate_limits,
        "bulk_deferred": bulk_deferred,
      },
    )
  if progress_fn is not None and bulk_deferred:
    progress_fn(
      "circuit breaker: "
      f"deferred {bulk_deferred} remaining variable pages "
      f"(failed={failed_count} deferred={deferred_count})"
    )
  return archived_count, skipped_count, failed_count, deferred_count, rows_processed


def run_archive(
  config: ArchiveConfig,
  *,
  read_inventory_fn: Callable[[Path], list[InventoryRow]] = read_inventory_csv,
  download_url_fn: Callable[[str, float, str], DownloadResult] = download_url,
  now_utc_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
  sleep_fn: Callable[[float], None] = _sleep,
  progress_fn: Callable[[str], None] | None = None,
) -> tuple[ArchiveResult, Path]:
  inventory_rows = read_inventory_fn(config.inventory_path)
  inventory_row_count = len(inventory_rows)
  sorted_rows = sorted(inventory_rows, key=_archive_order_key)
  manifest_rows: list[ArchiveManifestRow] = []
  archived_count = 0
  skipped_count = 0
  failed_count = 0
  deferred_count = 0
  rows_processed = 0
  previous_manifest = _read_trusted_previous_manifest(config.manifest_output_path)
  previous_manifest_rows = _read_previous_manifest_rows(config.manifest_output_path)
  consecutive_rate_limits = 0
  bulk_defer_remaining = False
  download_attempts = 0
  variable_page_count = sum(
    1 for row in inventory_rows if row.resource_kind == "variable_page"
  )

  init_progress_log(config.progress_log_path)
  append_progress_event(
    config.progress_log_path,
    phase="archive",
    event="start",
    message=f"inventory={config.inventory_path}",
    counts={"inventory_rows": inventory_row_count},
  )

  if (
    variable_page_count > VARIABLE_PAGE_BATCH_WARNING_THRESHOLD
    and not config.retry_failed_only
    and config.max_downloads is None
  ):
    warning_message = (
      f"warning: inventory contains {variable_page_count} variable_page rows; "
      "use bounded Phase 1B batches (see docs/pipeline.md) to avoid rate limits"
    )
    print(warning_message, file=sys.stderr, flush=True)
    if progress_fn is not None:
      progress_fn(warning_message)
    append_progress_event(
      config.progress_log_path,
      phase="archive",
      event="preflight_warning",
      message=warning_message,
      counts={"variable_page_count": variable_page_count},
    )

  def advance_row_progress(*, circuit_breaker_open: bool = False) -> None:
    nonlocal rows_processed
    rows_processed = _advance_archive_row_progress(
      config,
      progress_fn,
      rows_processed=rows_processed,
      inventory_rows=inventory_row_count,
      archived_count=archived_count,
      skipped_count=skipped_count,
      failed_count=failed_count,
      deferred_count=deferred_count,
      download_attempts=download_attempts,
      consecutive_rate_limits=consecutive_rate_limits,
      circuit_breaker_open=circuit_breaker_open,
    )

  for row_index, row in enumerate(sorted_rows):
    previous_row = previous_manifest_rows.get(row.url)
    if not _should_archive(row):
      manifest_row = _manifest_row_for_skip(row)
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="skip",
        url=row.url,
        resource_kind=row.resource_kind,
        status=row.http_status,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        ),
      )
      advance_row_progress()
      continue

    downloaded_at_utc = now_utc_fn().isoformat().replace("+00:00", "Z")
    if config.retry_failed_only and previous_row is None:
      manifest_row = _manifest_row_for_not_attempted(
        row,
        "not attempted because retry-failed-only requires a previous manifest row",
      )
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="retry_skip",
        message="no previous manifest row in retry-failed-only mode",
        url=row.url,
        resource_kind=row.resource_kind,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        ),
      )
      advance_row_progress()
      continue

    if (
      config.retry_failed_only
      and previous_row is not None
      and not _is_retriable_archive_state(previous_row.archive_state)
    ):
      if previous_row.archive_state == "archived" and not _previous_archive_row_is_trusted(
        previous_row
      ):
        manifest_row = _download_failure(
          row,
          "previous archived row is missing or checksum does not match",
          downloaded_at_utc,
        )
      else:
        manifest_row = previous_row
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="carry_forward",
        url=row.url,
        resource_kind=row.resource_kind,
        status=previous_row.http_status,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        ),
      )
      advance_row_progress()
      continue

    if config.max_downloads is not None and download_attempts >= config.max_downloads:
      if previous_row is not None:
        manifest_row = previous_row
      else:
        manifest_row = _download_failure(
          row,
          "not attempted because max downloads reached",
          downloaded_at_utc,
        )
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="download_limit",
        message="not attempted because max downloads reached",
        url=row.url,
        resource_kind=row.resource_kind,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        )
        | {"download_attempts": download_attempts},
      )
      advance_row_progress()
      continue

    url_error = _archive_url_error(row.url)
    if url_error:
      manifest_row = _download_failure(row, url_error, downloaded_at_utc)
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      consecutive_rate_limits = 0
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="download_failure",
        url=row.url,
        resource_kind=row.resource_kind,
        status=row.http_status,
        error=url_error,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        ),
      )
      advance_row_progress()
      continue

    local_path = archive_path_for_row(row, config.raw_root)
    if (
      local_path.is_file()
      and local_path.stat().st_size > 0
      and _existing_file_is_trusted(row, local_path, previous_manifest)
    ):
      manifest_row = _manifest_row_for_existing_file(
        row,
        downloaded_at_utc=downloaded_at_utc,
        local_path=local_path,
      )
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      consecutive_rate_limits = 0
      append_progress_event(
        config.progress_log_path,
        phase="archive",
        event="reuse",
        url=row.url,
        resource_kind=row.resource_kind,
        status=row.http_status,
        counts=_count_map(
          archived_count=archived_count,
          skipped_count=skipped_count,
          failed_count=failed_count,
          deferred_count=deferred_count,
        ),
      )
      advance_row_progress()
      continue

    if config.request_delay_seconds:
      sleep_fn(config.request_delay_seconds)
    download_attempts += 1
    download = download_url_fn(row.url, config.timeout_seconds, config.user_agent)

    if download.status is None or download.status >= 400 or not download.body:
      manifest_row = _manifest_row_for_failure(row, download, downloaded_at_utc)
      manifest_rows.append(manifest_row)
      archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
        manifest_row,
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      )
      if download.status == 429:
        consecutive_rate_limits += 1
        append_progress_event(
          config.progress_log_path,
          phase="archive",
          event="rate_limited",
          url=row.url,
          resource_kind=row.resource_kind,
          status=download.status,
          error=download.error,
          counts=_count_map(
            archived_count=archived_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            deferred_count=deferred_count,
          )
          | {"consecutive_rate_limits": consecutive_rate_limits},
        )
        if (
          row.resource_kind == "variable_page"
          and consecutive_rate_limits >= config.max_consecutive_rate_limits
        ):
          bulk_defer_remaining = True
        if config.rate_limit_cooldown_seconds:
          sleep_fn(config.rate_limit_cooldown_seconds)
      else:
        consecutive_rate_limits = 0
        append_progress_event(
          config.progress_log_path,
          phase="archive",
          event="download_failure",
          url=row.url,
          resource_kind=row.resource_kind,
          status=download.status,
          error=download.error,
          counts=_count_map(
            archived_count=archived_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            deferred_count=deferred_count,
          ),
        )
      advance_row_progress(circuit_breaker_open=bulk_defer_remaining)
      if bulk_defer_remaining:
        archived_count, skipped_count, failed_count, deferred_count, rows_processed = (
          _bulk_defer_remaining_rows(
            config,
            progress_fn,
            sorted_rows=sorted_rows,
            start_index=row_index + 1,
            manifest_rows=manifest_rows,
            archived_count=archived_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            deferred_count=deferred_count,
            rows_processed=rows_processed,
            inventory_row_count=inventory_row_count,
            download_attempts=download_attempts,
            consecutive_rate_limits=consecutive_rate_limits,
            now_utc_fn=now_utc_fn,
            previous_manifest_rows=previous_manifest_rows,
          )
        )
        break
      continue

    consecutive_rate_limits = 0
    local_path.parent.mkdir(parents=True, exist_ok=True)
    sha256 = _write_bytes_atomically(local_path, download.body)
    manifest_row = _manifest_row_for_success(
      row,
      http_status=download.status,
      content_type=download.content_type or row.content_type,
      downloaded_at_utc=downloaded_at_utc,
      sha256=sha256,
      local_path=local_path,
    )
    manifest_rows.append(manifest_row)
    archived_count, skipped_count, failed_count, deferred_count = _increment_counts(
      manifest_row,
      archived_count=archived_count,
      skipped_count=skipped_count,
      failed_count=failed_count,
      deferred_count=deferred_count,
    )
    append_progress_event(
      config.progress_log_path,
      phase="archive",
      event="download_success",
      url=row.url,
      resource_kind=row.resource_kind,
      status=download.status,
      counts=_count_map(
        archived_count=archived_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        deferred_count=deferred_count,
      ),
    )
    advance_row_progress()

  if (
    config.progress_interval > 0
    and rows_processed > 0
    and rows_processed % config.progress_interval != 0
  ):
    _emit_archive_periodic_progress(
      config,
      progress_fn,
      rows_processed=rows_processed,
      inventory_rows=inventory_row_count,
      archived_count=archived_count,
      skipped_count=skipped_count,
      failed_count=failed_count,
      deferred_count=deferred_count,
      download_attempts=download_attempts,
      consecutive_rate_limits=consecutive_rate_limits,
      circuit_breaker_open=bulk_defer_remaining,
      force=True,
    )

  result = ArchiveResult(
    config=config,
    inventory_rows=len(inventory_rows),
    manifest_rows=manifest_rows,
    archived_count=archived_count,
    skipped_count=skipped_count,
    failed_count=failed_count,
    deferred_count=deferred_count,
  )
  write_archive_manifest(manifest_rows, config.manifest_output_path)
  summary_path = write_archive_workspace_summary(result)
  complete_counts = {
    "rows_processed": rows_processed,
    "inventory_rows": inventory_row_count,
    "archived": archived_count,
    "skipped": skipped_count,
    "failed": failed_count,
    "deferred": deferred_count,
    "download_attempts": download_attempts,
    "manifest_rows": len(manifest_rows),
  }
  append_progress_event(
    config.progress_log_path,
    phase="archive",
    event="complete",
    counts=complete_counts,
  )
  if progress_fn is not None:
    deferred_suffix = f" deferred={deferred_count}" if deferred_count else ""
    progress_fn(
      "complete: "
      f"archived={archived_count} skipped={skipped_count} failed={failed_count}"
      f"{deferred_suffix} manifest_rows={len(manifest_rows)}"
    )
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
  parser.add_argument(
    "--max-consecutive-rate-limits",
    type=int,
    default=5,
    help="Defer remaining variable pages after this many consecutive HTTP 429 responses.",
  )
  parser.add_argument(
    "--retry-failed-only",
    action="store_true",
    help="Only retry rows that failed or were deferred in the previous archive manifest.",
  )
  parser.add_argument(
    "--max-downloads",
    type=int,
    default=None,
    help="Maximum fresh network download attempts for this archive run.",
  )
  parser.add_argument(
    "--rate-limit-cooldown-seconds",
    type=float,
    default=0.0,
    help="Additional cooldown after a final HTTP 429 response.",
  )
  parser.add_argument(
    "--progress-log",
    type=Path,
    default=Path("_workspace/03_archive_progress.jsonl"),
  )
  parser.add_argument("--no-progress-log", action="store_true")
  parser.add_argument(
    "--progress-interval",
    type=int,
    default=25,
    help="Emit rollup progress after this many processed inventory rows; use 0 to disable.",
  )
  return parser


def _print_progress(message: str) -> None:
  print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  try:
    config = ArchiveConfig(
      inventory_path=args.inventory,
      raw_root=args.raw_root,
      manifest_output_path=args.manifest_output,
      workspace_dir=args.workspace_dir,
      timeout_seconds=args.timeout_seconds,
      request_delay_seconds=args.request_delay_seconds,
      max_consecutive_rate_limits=args.max_consecutive_rate_limits,
      retry_failed_only=args.retry_failed_only,
      max_downloads=args.max_downloads,
      rate_limit_cooldown_seconds=args.rate_limit_cooldown_seconds,
      progress_log_path=None if args.no_progress_log else args.progress_log,
      progress_interval=args.progress_interval,
    )
  except ValueError as exc:
    print(f"error: {exc}", file=sys.stderr)
    return 2
  result, summary_path = run_archive(config, progress_fn=_print_progress)
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
