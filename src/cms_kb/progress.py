"""Lightweight JSONL progress logging for long CMS KB pipeline phases."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ProgressEvent(BaseModel):
  timestamp_utc: str
  phase: str
  event: str
  message: str = ""
  url: str = ""
  resource_kind: str = ""
  status: int | None = None
  counts: dict[str, int] = Field(default_factory=dict)
  error: str = ""


def now_utc_timestamp() -> str:
  return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def init_progress_log(log_path: Path | None) -> None:
  if log_path is None:
    return
  log_path.parent.mkdir(parents=True, exist_ok=True)
  log_path.write_text("", encoding="utf-8")


def append_progress_event(
  log_path: Path | None,
  *,
  phase: str,
  event: str,
  message: str = "",
  url: str = "",
  resource_kind: str = "",
  status: int | None = None,
  counts: dict[str, int] | None = None,
  error: str = "",
  timestamp_utc: str | None = None,
) -> None:
  if log_path is None:
    return
  log_path.parent.mkdir(parents=True, exist_ok=True)
  progress_event = ProgressEvent(
    timestamp_utc=timestamp_utc or now_utc_timestamp(),
    phase=phase,
    event=event,
    message=message,
    url=url,
    resource_kind=resource_kind,
    status=status,
    counts=counts or {},
    error=error,
  )
  with log_path.open("a", encoding="utf-8") as handle:
    handle.write(progress_event.model_dump_json(exclude_none=True) + "\n")
    handle.flush()


def _read_last_text_lines(log_path: Path, line_count: int) -> list[str]:
  chunk_size = 8192
  with log_path.open("rb") as handle:
    handle.seek(0, 2)
    file_size = handle.tell()
    if file_size == 0:
      return []

    buffer = b""
    position = file_size
    lines_found = 0
    while position > 0:
      read_size = min(chunk_size, position)
      position -= read_size
      handle.seek(position)
      chunk = handle.read(read_size)
      buffer = chunk + buffer
      lines_found += chunk.count(b"\n")
      if lines_found > line_count:
        break

    return [
      line.decode("utf-8", errors="replace")
      for line in buffer.splitlines()[-line_count:]
    ]


def read_progress_tail(log_path: Path, line_count: int) -> list[ProgressEvent]:
  if line_count < 1:
    raise ValueError("line_count must be at least 1")
  if not log_path.is_file():
    raise FileNotFoundError(f"progress log does not exist: {log_path}")
  lines = _read_last_text_lines(log_path, line_count)
  events: list[ProgressEvent] = []
  for line_number, line in enumerate(lines, start=1):
    if not line.strip():
      continue
    try:
      payload: Any = json.loads(line)
      events.append(ProgressEvent.model_validate(payload))
    except Exception as exc:
      raise ValueError(f"failed to parse progress JSONL tail line {line_number}: {exc}") from exc
  return events


def summarize_progress_events(events: list[ProgressEvent]) -> dict[str, object]:
  event_counts = Counter(event.event for event in events)
  last_success = next(
    (
      event
      for event in reversed(events)
      if event.event in {"download_success", "reuse", "progress", "complete"}
    ),
    None,
  )
  last_event = events[-1] if events else None
  return {
    "events": len(events),
    "event_counts": dict(sorted(event_counts.items())),
    "last_event": last_event.model_dump() if last_event is not None else None,
    "last_success": last_success.model_dump() if last_success is not None else None,
  }


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Summarize the tail of a CMS KB progress JSONL log."
  )
  parser.add_argument("log_path", type=Path)
  parser.add_argument("--lines", type=int, default=50)
  parser.add_argument("--json", action="store_true")
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  try:
    events = read_progress_tail(args.log_path, args.lines)
    summary = summarize_progress_events(events)
  except Exception as exc:
    print(f"Error reading progress log: {exc}", file=sys.stderr)
    return 1

  if args.json:
    print(json.dumps(summary, indent=2, sort_keys=True))
  else:
    print(f"events: {summary['events']}")
    print(f"event_counts: {summary['event_counts']}")
    last_event = summary["last_event"]
    if isinstance(last_event, dict):
      print(
        "last_event: "
        f"{last_event.get('timestamp_utc')} {last_event.get('phase')} "
        f"{last_event.get('event')} {last_event.get('url') or ''}"
      )
  return 0


__all__ = [
  "ProgressEvent",
  "append_progress_event",
  "build_arg_parser",
  "init_progress_log",
  "main",
  "read_progress_tail",
  "summarize_progress_events",
]
