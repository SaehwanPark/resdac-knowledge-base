from __future__ import annotations

from pathlib import Path

from cms_kb.progress import (
  append_progress_event,
  init_progress_log,
  read_progress_tail,
  summarize_progress_events,
)


def test_progress_tail_summary_reports_last_events(tmp_path: Path) -> None:
  log_path = tmp_path / "_workspace" / "progress.jsonl"
  append_progress_event(
    log_path,
    stage="archive",
    event="start",
    counts={"inventory_rows": 2},
    timestamp_utc="2026-06-16T00:00:00Z",
  )
  append_progress_event(
    log_path,
    stage="archive",
    event="download_success",
    url="https://example.com/source",
    counts={"archived": 1},
    timestamp_utc="2026-06-16T00:00:01Z",
  )
  append_progress_event(
    log_path,
    stage="archive",
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


def test_init_progress_log_truncates_existing_file(tmp_path: Path) -> None:
  log_path = tmp_path / "progress.jsonl"
  log_path.write_text('{"event":"old"}\n', encoding="utf-8")

  init_progress_log(log_path)
  append_progress_event(log_path, stage="archive", event="start")

  assert log_path.read_text(encoding="utf-8").count("\n") == 1
  assert '"event":"start"' in log_path.read_text(encoding="utf-8")


def test_read_progress_tail_reads_large_file_efficiently(tmp_path: Path) -> None:
  log_path = tmp_path / "progress.jsonl"
  with log_path.open("w", encoding="utf-8") as handle:
    for index in range(5000):
      handle.write(
        f'{{"timestamp_utc":"2026-06-16T00:00:{index:02d}Z",'
        f'"stage":"archive","event":"skip","counts":{{"index":{index}}}}}\n'
      )

  events = read_progress_tail(log_path, 2)

  assert len(events) == 2
  assert events[-1].counts["index"] == 4999
