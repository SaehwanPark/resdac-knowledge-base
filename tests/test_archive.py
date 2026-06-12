from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
  skipped_row = InventoryRow(
    url="https://example.com/files/dead.pdf",
    title="Dead asset",
    resource_kind="asset",
    asset_kind="pdf",
    content_type="application/pdf",
    http_status=404,
    link_state="dead",
  )
  write_inventory_csv([html_row, asset_row, skipped_row], inventory_path)

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

  assert result.archived_count == 2
  assert result.skipped_count == 1
  assert result.failed_count == 0

  html_path = archive_path_for_row(html_row, tmp_path / "data" / "raw")
  asset_path = archive_path_for_row(asset_row, tmp_path / "data" / "raw")
  assert html_path.read_bytes() == downloads[html_row.url].body
  assert asset_path.read_bytes() == downloads[asset_row.url].body

  manifest_path = tmp_path / "manifests" / "archive_manifest.csv"
  with manifest_path.open(newline="", encoding="utf-8") as handle:
    manifest_rows = {row["url"]: row for row in csv.DictReader(handle)}

  assert manifest_rows[html_row.url]["archive_state"] == "archived"
  assert manifest_rows[html_row.url]["sha256"] == hashlib.sha256(
    downloads[html_row.url].body
  ).hexdigest()
  assert manifest_rows[asset_row.url]["local_path"] == str(asset_path)
  assert manifest_rows[skipped_row.url]["archive_state"] == "skipped"
  assert "not a live archive target" in manifest_rows[skipped_row.url]["error"]

  summary_text = summary_path.read_text(encoding="utf-8")
  assert "- Archived: 2" in summary_text
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
