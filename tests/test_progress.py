from __future__ import annotations

from pathlib import Path

from cms_kb.progress import (
  append_progress_event,
  read_progress_tail,
  summarize_progress_events,
)


def test_progress_tail_summary_reports_last_events(tmp_path: Path) -> None:
  log_path = tmp_path / "_workspace" / "progress.jsonl"
  append_progress_event(
    log_path,
    phase="archive",
    event="start",
    counts={"inventory_rows": 2},
    timestamp_utc="2026-06-16T00:00:00Z",
  )
  append_progress_event(
    log_path,
    phase="archive",
    event="download_success",
    url="https://example.com/source",
    counts={"archived": 1},
    timestamp_utc="2026-06-16T00:00:01Z",
  )
  append_progress_event(
    log_path,
    phase="archive",
    event="rate_limited",
    status=429,
    counts={"failed": 1},
    timestamp_utc="2026-06-16T00:00:02Z",
  )

  events = read_progress_tail(log_path, 2)
  summary = summarize_progress_events(events)

  assert [event.event for event in events] == ["download_success", "rate_limited"]
  assert summary["events"] == 2
  assert summary["event_counts"] == {
    "download_success": 1,
    "rate_limited": 1,
  }
  assert isinstance(summary["last_success"], dict)
