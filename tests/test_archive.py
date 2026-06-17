from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from cms_kb import archive
from cms_kb.archive import ArchiveConfig, DownloadResult, archive_path_for_row, run_archive
from cms_kb.inventory import InventoryRow, read_inventory_csv, write_inventory_csv


def test_read_inventory_csv_rejects_missing_columns(tmp_path: Path) -> None:
  input_path = tmp_path / "site_inventory.csv"
  input_path.write_text("url,title\nhttps://example.com,Example\n", encoding="utf-8")

  with pytest.raises(ValueError, match="missing required columns"):
    read_inventory_csv(input_path)


def test_run_archive_archives_live_html_and_assets_and_skips_non_live_rows(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  html_row = InventoryRow(
    url="https://resdac.org/cms-data?page=0",
    title="CMS Data",
    resource_kind="listing_page",
    content_type="text/html",
    http_status=200,
    link_state="live",
  )
  asset_row = InventoryRow(
    url="https://example.com/files/codebook.pdf",
    title="Codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
    source_url=html_row.url,
    source_title=html_row.title,
  )
  variable_row = InventoryRow(
    url="https://resdac.org/cms-data/variables/encrypted-ccw-beneficiary-id",
    title="Encrypted CCW Beneficiary ID",
    resource_kind="variable_page",
    link_state="unknown",
    source_url=html_row.url,
    source_title=html_row.title,
  )
  skipped_row = InventoryRow(
    url="https://example.com/files/dead.pdf",
    title="Dead asset",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=404,
    link_state="dead",
  )
  write_inventory_csv([html_row, asset_row, variable_row, skipped_row], inventory_path)

  downloads = {
    html_row.url: DownloadResult(
      url=html_row.url,
      status=200,
      content_type="text/html",
      body=b"<html><body>listing</body></html>",
    ),
    asset_row.url: DownloadResult(
      url=asset_row.url,
      status=200,
      content_type="application/pdf",
      body=b"%PDF-1.4 fake pdf",
    ),
    variable_row.url: DownloadResult(
      url=variable_row.url,
      status=200,
      content_type="text/html",
      body=b"<html><body>Encrypted CCW Beneficiary ID</body></html>",
    ),
  }

  result, summary_path = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=lambda url, timeout_seconds, user_agent: downloads[url],
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert result.archived_count == 3
  assert result.skipped_count == 1
  assert result.failed_count == 0

  html_path = archive_path_for_row(html_row, tmp_path / "data" / "raw")
  asset_path = archive_path_for_row(asset_row, tmp_path / "data" / "raw")
  variable_path = archive_path_for_row(variable_row, tmp_path / "data" / "raw")
  assert html_path.read_bytes() == downloads[html_row.url].body
  assert asset_path.read_bytes() == downloads[asset_row.url].body
  assert variable_path.read_bytes() == downloads[variable_row.url].body

  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  with manifest_path.open(newline="", encoding="utf-8") as handle:
    manifest_rows = {row["url"]: row for row in csv.DictReader(handle)}

  assert manifest_rows[html_row.url]["archive_state"] == "archived"
  assert manifest_rows[html_row.url]["sha256"] == hashlib.sha256(
    downloads[html_row.url].body
  ).hexdigest()
  assert manifest_rows[asset_row.url]["local_path"] == str(asset_path)
  assert manifest_rows[variable_row.url]["local_path"] == str(variable_path)
  assert manifest_rows[skipped_row.url]["archive_state"] == "skipped"
  assert "not a live archive target" in manifest_rows[skipped_row.url]["error"]

  summary_text = summary_path.read_text(encoding="utf-8")
  assert "- Archived: 3" in summary_text
  assert "- Skipped: 1" in summary_text
  assert "- Failed: 0" in summary_text


def test_run_archive_records_actual_download_status_in_success_manifest(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  asset_row = InventoryRow(
    url="https://example.com/files/codebook.pdf",
    title="Codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([asset_row], inventory_path)

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=lambda url, timeout_seconds, user_agent: DownloadResult(
      url=url,
      status=206,
      content_type="application/pdf",
      body=b"%PDF-1.4 fake pdf",
    ),
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  archived_row = result.manifest_rows[0]
  assert archived_row.archive_state == "archived"
  assert archived_row.http_status == 206


def test_run_archive_records_failed_live_download_and_continues_writing_outputs(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  live_row = InventoryRow(
    url="https://example.com/files/layout.xlsx",
    title="Layout",
    resource_kind="asset",
    asset_kind="xlsx",
    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([live_row], inventory_path)

  result, summary_path = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=lambda url, timeout_seconds, user_agent: DownloadResult(
      url=url,
      status=503,
      content_type=live_row.content_type,
      error="HTTP Error 503: Service Unavailable",
    ),
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert result.archived_count == 0
  assert result.failed_count == 1
  failed_row = result.manifest_rows[0]
  assert failed_row.archive_state == "failed"
  assert failed_row.http_status == 503
  assert "503" in failed_row.error

  summary_text = summary_path.read_text(encoding="utf-8")
  assert live_row.url in summary_text
  assert "HTTP Error 503" in summary_text


def test_run_archive_defers_variable_pages_after_repeated_rate_limits(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  rows = [
    InventoryRow(
      url=f"https://resdac.org/cms-data/variables/rate-limited-{idx}",
      title=f"Variable {idx}",
      resource_kind="variable_page",
      link_state="unknown",
    )
    for idx in range(3)
  ]
  write_inventory_csv(rows, inventory_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(
      url=url,
      status=429,
      content_type="text/html",
      error="HTTP Error 429: Too Many Requests",
    )

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
      max_consecutive_rate_limits=2,
      progress_log_path=tmp_path / "_workspace" / "archive_progress.jsonl",
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert result.failed_count == 3
  assert download_calls == [rows[0].url, rows[1].url]
  assert result.manifest_rows[2].error == (
    "deferred after repeated HTTP 429 rate limits"
  )
  log_text = (tmp_path / "_workspace" / "archive_progress.jsonl").read_text(
    encoding="utf-8"
  )
  assert '"event":"rate_limited"' in log_text
  assert '"event":"circuit_breaker"' in log_text


def test_run_archive_rejects_unsafe_live_inventory_url(tmp_path: Path) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  live_row = InventoryRow(
    url="file:///tmp/private.pdf",
    title="Private",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([live_row], inventory_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(url=url, status=200, body=b"unsafe")

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == []
  assert result.archived_count == 0
  assert result.failed_count == 1
  failed_row = result.manifest_rows[0]
  assert failed_row.archive_state == "failed"
  assert "absolute http(s)" in failed_row.error


def test_run_archive_reuses_existing_raw_file_without_download(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  live_row = InventoryRow(
    url="https://example.com/files/codebook.pdf",
    title="Codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([live_row], inventory_path)
  raw_root = tmp_path / "data" / "raw"
  existing_path = archive_path_for_row(live_row, raw_root)
  existing_path.parent.mkdir(parents=True, exist_ok=True)
  existing_path.write_bytes(b"%PDF-1.4 existing pdf")
  existing_sha = hashlib.sha256(b"%PDF-1.4 existing pdf").hexdigest()
  manifest_output_path = tmp_path / "manifests" / "archive_manifest.csv"
  archive.write_archive_manifest([
    archive.ArchiveManifestRow(
      url=live_row.url,
      resource_kind=live_row.resource_kind,
      asset_kind=live_row.asset_kind,
      content_type=live_row.content_type,
      http_status=live_row.http_status,
      archive_state="archived",
      downloaded_at_utc="2026-06-10T12:00:00Z",
      sha256=existing_sha,
      local_path=str(existing_path),
    )
  ], manifest_output_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(url=url, status=503, error="should not download")

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=raw_root,
      manifest_output_path=manifest_output_path,
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == []
  assert result.archived_count == 1
  assert result.failed_count == 0
  archived_row = result.manifest_rows[0]
  assert archived_row.archive_state == "archived"
  assert archived_row.local_path == str(existing_path)
  assert archived_row.sha256 == existing_sha


def test_run_archive_retry_failed_only_carries_forward_prior_successes(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  archived_row = InventoryRow(
    url="https://example.com/files/already-archived.pdf",
    title="Already archived",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  failed_row = InventoryRow(
    url="https://example.com/files/retry-me.pdf",
    title="Retry me",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([archived_row, failed_row], inventory_path)

  raw_root = tmp_path / "data" / "raw"
  existing_path = archive_path_for_row(archived_row, raw_root)
  existing_path.parent.mkdir(parents=True, exist_ok=True)
  existing_path.write_bytes(b"%PDF-1.4 archived")
  existing_sha = hashlib.sha256(b"%PDF-1.4 archived").hexdigest()
  manifest_output_path = tmp_path / "manifests" / "archive_manifest.csv"
  archive.write_archive_manifest([
    archive.ArchiveManifestRow(
      url=archived_row.url,
      resource_kind=archived_row.resource_kind,
      asset_kind=archived_row.asset_kind,
      content_type=archived_row.content_type,
      http_status=archived_row.http_status,
      archive_state="archived",
      downloaded_at_utc="2026-06-10T12:00:00Z",
      sha256=existing_sha,
      local_path=str(existing_path),
    ),
    archive.ArchiveManifestRow(
      url=failed_row.url,
      resource_kind=failed_row.resource_kind,
      asset_kind=failed_row.asset_kind,
      content_type=failed_row.content_type,
      http_status=429,
      archive_state="failed",
      downloaded_at_utc="2026-06-10T12:01:00Z",
      error="HTTP Error 429: Too Many Requests",
    ),
  ], manifest_output_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(
      url=url,
      status=200,
      content_type="application/pdf",
      body=b"%PDF-1.4 retried",
    )

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=raw_root,
      manifest_output_path=manifest_output_path,
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
      retry_failed_only=True,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == [failed_row.url]
  assert result.archived_count == 2
  assert result.failed_count == 0
  rows_by_url = {row.url: row for row in result.manifest_rows}
  assert rows_by_url[archived_row.url].local_path == str(existing_path)
  assert rows_by_url[failed_row.url].archive_state == "archived"


def test_run_archive_retry_failed_only_skips_rows_missing_previous_manifest(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  new_row = InventoryRow(
    url="https://example.com/files/new-codebook.pdf",
    title="New codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([new_row], inventory_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(url=url, status=200, body=b"should not download")

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
      retry_failed_only=True,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == []
  assert result.skipped_count == 1
  assert result.failed_count == 0
  assert result.manifest_rows[0].archive_state == "skipped"
  assert "retry-failed-only" in result.manifest_rows[0].error


def test_run_archive_skips_current_non_live_row_despite_previous_archive(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  dead_row = InventoryRow(
    url="https://example.com/files/dead-codebook.pdf",
    title="Dead codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=404,
    link_state="dead",
  )
  write_inventory_csv([dead_row], inventory_path)
  raw_root = tmp_path / "data" / "raw"
  archived_path = archive_path_for_row(dead_row, raw_root)
  archived_path.parent.mkdir(parents=True, exist_ok=True)
  archived_path.write_bytes(b"%PDF-1.4 stale")
  manifest_output_path = tmp_path / "manifests" / "archive_manifest.csv"
  archive.write_archive_manifest([
    archive.ArchiveManifestRow(
      url=dead_row.url,
      resource_kind=dead_row.resource_kind,
      asset_kind=dead_row.asset_kind,
      content_type=dead_row.content_type,
      http_status=200,
      archive_state="archived",
      downloaded_at_utc="2026-06-10T12:00:00Z",
      sha256=hashlib.sha256(b"%PDF-1.4 stale").hexdigest(),
      local_path=str(archived_path),
    )
  ], manifest_output_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(url=url, status=200, body=b"should not download")

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=raw_root,
      manifest_output_path=manifest_output_path,
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == []
  assert result.archived_count == 0
  assert result.skipped_count == 1
  assert result.manifest_rows[0].archive_state == "skipped"
  assert result.manifest_rows[0].http_status == 404


def test_run_archive_max_downloads_limits_fresh_network_attempts(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  rows = [
    InventoryRow(
      url=f"https://example.com/files/codebook-{idx}.pdf",
      title=f"Codebook {idx}",
      resource_kind="asset",
      asset_kind="pdf",
      content_type="application/pdf",
      http_status=200,
      link_state="live",
    )
    for idx in range(2)
  ]
  write_inventory_csv(rows, inventory_path)
  download_calls: list[str] = []

  def fake_download(
    url: str, timeout_seconds: float, user_agent: str
  ) -> DownloadResult:
    download_calls.append(url)
    return DownloadResult(
      url=url,
      status=200,
      content_type="application/pdf",
      body=b"%PDF-1.4 downloaded",
    )

  result, _ = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
      max_downloads=1,
    ),
    download_url_fn=fake_download,
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=lambda seconds: None,
  )

  assert download_calls == [rows[0].url]
  assert result.archived_count == 1
  assert result.failed_count == 1
  assert result.manifest_rows[1].error == "not attempted because max downloads reached"


def test_run_archive_sleeps_after_rate_limit_cooldown(
  tmp_path: Path,
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  row = InventoryRow(
    url="https://resdac.org/cms-data/variables/rate-limited",
    title="Rate limited",
    resource_kind="variable_page",
    link_state="unknown",
  )
  write_inventory_csv([row], inventory_path)
  sleep_calls: list[float] = []

  result, summary_path = run_archive(
    ArchiveConfig(
      inventory_path=inventory_path,
      raw_root=tmp_path / "data" / "raw",
      manifest_output_path=tmp_path / "manifests" / "archive_manifest.csv",
      workspace_dir=tmp_path / "_workspace",
      request_delay_seconds=0.0,
      rate_limit_cooldown_seconds=300.0,
    ),
    download_url_fn=lambda url, timeout_seconds, user_agent: DownloadResult(
      url=url,
      status=429,
      content_type="text/html",
      error="HTTP Error 429: Too Many Requests",
    ),
    now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    sleep_fn=sleep_calls.append,
  )

  assert result.failed_count == 1
  assert sleep_calls == [300.0]
  summary_text = summary_path.read_text(encoding="utf-8")
  assert "--retry-failed-only --max-downloads 50" in summary_text


def test_archive_config_rejects_negative_retry_controls() -> None:
  with pytest.raises(ValueError, match="max_downloads"):
    ArchiveConfig(max_downloads=-1)

  with pytest.raises(ValueError, match="rate_limit_cooldown_seconds"):
    ArchiveConfig(rate_limit_cooldown_seconds=-1)


def test_run_archive_rejects_invalid_previous_manifest_row(tmp_path: Path) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  row = InventoryRow(
    url="https://example.com/files/codebook.pdf",
    title="Codebook",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=200,
    link_state="live",
  )
  write_inventory_csv([row], inventory_path)
  manifest_output_path = tmp_path / "manifests" / "archive_manifest.csv"
  manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
  manifest_output_path.write_text(
    ",".join(archive.ARCHIVE_MANIFEST_FIELDNAMES)
    + "\n"
    + ",".join([
      row.url,
      "bad_kind",
      "pdf",
      "",
      "",
      "application/pdf",
      "200",
      "archived",
      "2026-06-10T12:00:00Z",
      "not-a-real-sha",
      "data/raw/assets/pdf/example.pdf",
      "",
    ])
    + "\n",
    encoding="utf-8",
  )

  with pytest.raises(ValidationError, match="resource_kind"):
    run_archive(
      ArchiveConfig(
        inventory_path=inventory_path,
        raw_root=tmp_path / "data" / "raw",
        manifest_output_path=manifest_output_path,
        workspace_dir=tmp_path / "_workspace",
        request_delay_seconds=0.0,
        retry_failed_only=True,
      ),
      download_url_fn=lambda url, timeout_seconds, user_agent: DownloadResult(
        url=url,
        status=200,
        body=b"should not download",
      ),
      now_utc_fn=lambda: datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
      sleep_fn=lambda seconds: None,
    )


def test_archive_main_returns_nonzero_when_failures_are_present(
  monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
  inventory_path = tmp_path / "site_inventory.csv"
  manifest_output_path = tmp_path / "manifests" / "archive_manifest.csv"
  workspace_dir = tmp_path / "_workspace"

  def fake_run_archive(config: ArchiveConfig) -> tuple[archive.ArchiveResult, Path]:
    return (
      archive.ArchiveResult(
        config=config,
        inventory_rows=1,
        manifest_rows=[],
        archived_count=0,
        skipped_count=0,
        failed_count=1,
      ),
      workspace_dir / "03_archive_manifest.md",
    )

  monkeypatch.setattr(archive, "run_archive", fake_run_archive)

  exit_code = archive.main(
    [
      "--inventory",
      str(inventory_path),
      "--manifest-output",
      str(manifest_output_path),
      "--workspace-dir",
      str(workspace_dir),
      "--raw-root",
      str(tmp_path / "data" / "raw"),
      "--request-delay-seconds",
      "0",
    ]
  )

  assert exit_code == 1
