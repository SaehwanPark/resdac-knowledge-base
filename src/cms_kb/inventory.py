"""Discovery-only inventory crawl for CMS data documentation pages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator

ResourceKind = Literal[
  "listing_page", "dataset_page", "documentation_page", "asset", "other"
]
LinkState = Literal["live", "dead", "unknown"]
INVENTORY_FIELDNAMES = [
  "url",
  "title",
  "resource_kind",
  "asset_kind",
  "content_type",
  "http_status",
  "link_state",
  "linked_documents",
  "source_url",
  "source_title",
]


def _normalize_whitespace(text: str) -> str:
  return re.sub(r"\s+", " ", text).strip()


def _strip_www(netloc: str) -> str:
  return netloc[4:] if netloc.startswith("www.") else netloc


def normalize_url(base_url: str, href: str) -> str:
  absolute = urljoin(base_url, href)
  parts = urlparse(absolute)
  path = parts.path
  if path != "/" and path.endswith("/"):
    path = path.rstrip("/")
  return urlunparse(
    (
      parts.scheme.lower(),
      _strip_www(parts.netloc.lower()),
      path,
      parts.params,
      parts.query,
      "",
    )
  )


def classify_resource_kind(url: str) -> ResourceKind:
  parts = urlparse(url)
  path = parts.path.lower()
  if path == "/cms-data":
    return "listing_page"
  if path.endswith("/data-documentation"):
    return "documentation_page"
  if "/cms-data/files/" in path:
    return "dataset_page"
  if path.endswith((".pdf", ".xlsx", ".xls", ".csv", ".zip")):
    return "asset"
  return "other"


def classify_asset_kind(url: str, content_type: str | None) -> str:
  path = urlparse(url).path.lower()
  if path.endswith(".pdf") or content_type == "application/pdf":
    return "pdf"
  if path.endswith(".xlsx") or content_type in {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
  }:
    return "xlsx"
  if path.endswith(".xls"):
    return "xls"
  if path.endswith(".csv") or content_type == "text/csv":
    return "csv"
  if path.endswith(".zip") or content_type == "application/zip":
    return "zip"
  return "other"


def build_listing_url(base_url: str, page_number: int) -> str:
  parts = urlparse(base_url)
  query = dict(parse_qsl(parts.query, keep_blank_values=True))
  query["page"] = str(page_number)
  return urlunparse(
    (parts.scheme, parts.netloc, parts.path, parts.params, urlencode(query), "")
  )


class InventoryConfig(BaseModel):
  base_url: str = "https://resdac.org/cms-data"
  max_pages: int = 4
  max_follow_pages: int | None = None
  max_assets: int | None = None
  timeout_seconds: float = 20.0
  request_delay_seconds: float = 0.0
  progress_interval: int = 25
  user_agent: str = "Mozilla/5.0 (compatible; cms-kb-inventory/0.1)"
  output_path: Path = Path("manifests/site_inventory.csv")
  workspace_dir: Path = Path("_workspace")

  @field_validator("base_url")
  @classmethod
  def _validate_base_url(cls, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
      raise ValueError("base_url must be an absolute http(s) URL")
    return value.rstrip("/")

  @field_validator("max_pages")
  @classmethod
  def _validate_max_pages(cls, value: int) -> int:
    if value < 1:
      raise ValueError("max_pages must be at least 1")
    return value

  @field_validator("max_follow_pages", "max_assets")
  @classmethod
  def _validate_optional_non_negative_int(cls, value: int | None) -> int | None:
    if value is not None and value < 0:
      raise ValueError("crawl limits cannot be negative")
    return value

  @field_validator("request_delay_seconds")
  @classmethod
  def _validate_request_delay_seconds(cls, value: float) -> float:
    if value < 0:
      raise ValueError("request_delay_seconds cannot be negative")
    return value

  @field_validator("progress_interval")
  @classmethod
  def _validate_progress_interval(cls, value: int) -> int:
    if value < 0:
      raise ValueError("progress_interval cannot be negative")
    return value


class HtmlFetchResult(BaseModel):
  url: str
  status: int
  content_type: str | None = None
  html: str


class ProbeResult(BaseModel):
  url: str
  status: int | None = None
  content_type: str | None = None


class InventoryRow(BaseModel):
  url: str
  title: str = ""
  resource_kind: ResourceKind = "other"
  asset_kind: str = ""
  content_type: str = ""
  http_status: int | None = None
  link_state: LinkState = "unknown"
  linked_documents: int = 0
  source_url: str = ""
  source_title: str = ""


class InventoryResult(BaseModel):
  config: InventoryConfig
  rows: list[InventoryRow] = Field(default_factory=list)
  summary: dict[str, int] = Field(default_factory=dict)
  dead_links: list[InventoryRow] = Field(default_factory=list)
  duplicates_skipped: int = 0


def read_inventory_csv(input_path: Path) -> list[InventoryRow]:
  with input_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
      raise ValueError(f"inventory CSV has no header: {input_path}")

    missing_fieldnames = [
      fieldname
      for fieldname in INVENTORY_FIELDNAMES
      if fieldname not in reader.fieldnames
    ]
    if missing_fieldnames:
      raise ValueError(
        f"inventory CSV is missing required columns: {', '.join(missing_fieldnames)}"
      )

    rows: list[InventoryRow] = []
    for raw_row in reader:
      normalized_row = {
        "url": raw_row["url"],
        "title": raw_row["title"],
        "resource_kind": raw_row["resource_kind"],
        "asset_kind": raw_row["asset_kind"],
        "content_type": raw_row["content_type"],
        "http_status": (
          int(raw_row["http_status"]) if raw_row["http_status"].strip() else None
        ),
        "link_state": raw_row["link_state"],
        "linked_documents": int(raw_row["linked_documents"] or 0),
        "source_url": raw_row["source_url"],
        "source_title": raw_row["source_title"],
      }
      rows.append(InventoryRow.model_validate(normalized_row))
  return rows


@dataclass(frozen=True)
class ParsedLink:
  href: str
  text: str


class _PageParser(HTMLParser):
  def __init__(self) -> None:
    super().__init__()
    self.title_parts: list[str] = []
    self.h1_parts: list[str] = []
    self.links: list[ParsedLink] = []
    self._in_title = False
    self._in_h1 = False
    self._in_a = False
    self._current_href: str = ""
    self._current_text: list[str] = []

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    attributes = dict(attrs)
    if tag == "title":
      self._in_title = True
    elif tag == "h1" and not self.h1_parts:
      self._in_h1 = True
    elif tag == "a":
      href = attributes.get("href")
      if href:
        self._in_a = True
        self._current_href = href
        self._current_text = []

  def handle_data(self, data: str) -> None:
    if self._in_title:
      self.title_parts.append(data)
    if self._in_h1:
      self.h1_parts.append(data)
    if self._in_a:
      self._current_text.append(data)

  def handle_endtag(self, tag: str) -> None:
    if tag == "title":
      self._in_title = False
    elif tag == "h1":
      self._in_h1 = False
    elif tag == "a" and self._in_a:
      self.links.append(
        ParsedLink(
          href=self._current_href,
          text=_normalize_whitespace("".join(self._current_text)),
        )
      )
      self._in_a = False
      self._current_href = ""
      self._current_text = []


def parse_page(html: str) -> tuple[str, list[ParsedLink]]:
  parser = _PageParser()
  parser.feed(html)
  title = _normalize_whitespace("".join(parser.title_parts))
  if not title:
    title = _normalize_whitespace("".join(parser.h1_parts))
  return title, parser.links


def is_relevant_href(base_url: str, href: str) -> bool:
  absolute = normalize_url(base_url, href)
  parts = urlparse(absolute)
  path = parts.path.lower()
  if path.startswith("/cms-data/files/"):
    return True
  if path.endswith((".pdf", ".xlsx", ".xls", ".csv", ".zip")):
    return True
  return False


def _link_is_documentation(base_url: str, href: str) -> bool:
  return classify_resource_kind(normalize_url(base_url, href)) == "documentation_page"


def _link_is_dataset_page(base_url: str, href: str) -> bool:
  return classify_resource_kind(normalize_url(base_url, href)) == "dataset_page"


def _link_is_asset(base_url: str, href: str) -> bool:
  return classify_resource_kind(normalize_url(base_url, href)) == "asset"


def _empty_row(
  url: str, *, source_url: str = "", source_title: str = "", title: str = ""
) -> InventoryRow:
  return InventoryRow(
    url=url,
    title=title,
    resource_kind=classify_resource_kind(url),
    source_url=source_url,
    source_title=source_title,
  )


def _request_with_retry(
  request: Request,
  *,
  timeout_seconds: float,
  retry_statuses: set[int],
  read_body: bool,
) -> tuple[int, str | None, str]:
  delay_seconds = 1.0
  for attempt in range(3):
    try:
      with urlopen(request, timeout=timeout_seconds) as response:
        body = (
          response.read().decode("utf-8", errors="replace")
          if read_body
          else None
        )
        return (
          int(response.status),
          response.headers.get_content_type(),
          body or "",
        )
    except HTTPError as exc:
      if exc.code in retry_statuses and attempt < 2:
        retry_after = (
          exc.headers.get("Retry-After") if exc.headers is not None else None
        )
        sleep_seconds = (
          float(retry_after)
          if retry_after and retry_after.isdigit()
          else delay_seconds
        )
        time.sleep(sleep_seconds)
        delay_seconds *= 2
        continue
      content_type = (
        exc.headers.get_content_type() if exc.headers is not None else None
      )
      return int(exc.code), content_type, ""
    except URLError:
      if attempt < 2:
        time.sleep(delay_seconds)
        delay_seconds *= 2
        continue
      return 0, None, ""
  return 0, None, ""


def fetch_html(url: str, timeout_seconds: float, user_agent: str) -> HtmlFetchResult:
  request = Request(url, headers={"User-Agent": user_agent}, method="GET")
  status, content_type, html = _request_with_retry(
    request,
    timeout_seconds=timeout_seconds,
    retry_statuses={429, 500, 502, 503, 504},
    read_body=True,
  )
  return HtmlFetchResult(url=url, status=status, content_type=content_type, html=html)


def probe_url(url: str, timeout_seconds: float, user_agent: str) -> ProbeResult:
  attempts: list[tuple[str, dict[str, str]]] = [
    ("HEAD", {}),
    ("GET", {"Range": "bytes=0-0"}),
  ]
  for method, extra_headers in attempts:
    headers = {"User-Agent": user_agent, **extra_headers}
    request = Request(url, headers=headers, method=method)
    status, content_type, _ = _request_with_retry(
      request,
      timeout_seconds=timeout_seconds,
      retry_statuses={429, 500, 502, 503, 504},
      read_body=False,
    )
    if status == 0 and content_type is None:
      if method == "HEAD":
        continue
      return ProbeResult(url=url, status=None, content_type=None)
    if method == "HEAD" and status in {405, 501}:
      continue
    return ProbeResult(url=url, status=status, content_type=content_type)
  return ProbeResult(url=url, status=None, content_type=None)


def _register_row(
  rows: dict[str, InventoryRow],
  duplicates_skipped: list[int],
  *,
  url: str,
  title: str = "",
  source_url: str = "",
  source_title: str = "",
) -> InventoryRow:
  existing = rows.get(url)
  if existing is not None:
    duplicates_skipped[0] += 1
    if not existing.title and title:
      existing.title = title
    if not existing.source_url and source_url:
      existing.source_url = source_url
    if not existing.source_title and source_title:
      existing.source_title = source_title
    return existing

  row = _empty_row(url, source_url=source_url, source_title=source_title, title=title)
  rows[url] = row
  return row


def _update_page_row(
  row: InventoryRow,
  *,
  title: str,
  content_type: str | None,
  status: int | None,
  linked_documents: int,
) -> None:
  if title and not row.title:
    row.title = title
  if content_type and not row.content_type:
    row.content_type = content_type
  if status is not None:
    row.http_status = status
    row.link_state = "live" if status < 400 else "dead"
  row.linked_documents = linked_documents


def _probe_asset_row(
  row: InventoryRow,
  config: InventoryConfig,
  *,
  probe_url_fn: Callable[[str, float, str], ProbeResult],
) -> None:
  if config.request_delay_seconds:
    time.sleep(config.request_delay_seconds)
  probe = probe_url_fn(row.url, config.timeout_seconds, config.user_agent)
  _update_probe_row(row, probe)


def _asset_probe_needed(row: InventoryRow) -> bool:
  return row.http_status is None and row.link_state == "unknown"


def _update_probe_row(row: InventoryRow, probe: ProbeResult) -> None:
  row.http_status = probe.status
  row.content_type = probe.content_type or row.content_type
  if probe.status is None:
    row.link_state = "unknown"
  else:
    row.link_state = "live" if probe.status < 400 else "dead"
  if not row.asset_kind:
    row.asset_kind = classify_asset_kind(
      row.url, row.content_type or probe.content_type
    )


def _sorted_rows(rows: dict[str, InventoryRow]) -> list[InventoryRow]:
  order = {
    "listing_page": 0,
    "dataset_page": 1,
    "documentation_page": 2,
    "asset": 3,
    "other": 4,
  }
  return sorted(rows.values(), key=lambda row: (order[row.resource_kind], row.url))


def _count_dead_links(rows: list[InventoryRow]) -> list[InventoryRow]:
  return [row for row in rows if row.link_state == "dead"]


def _limit_reached(limit: int | None, count: int) -> bool:
  return limit is not None and count >= limit


def _emit_progress(
  progress_fn: Callable[[str], None] | None,
  message: str,
) -> None:
  if progress_fn is not None:
    progress_fn(message)


def _emit_periodic_progress(
  config: InventoryConfig,
  progress_fn: Callable[[str], None] | None,
  *,
  network_operations: int,
  listing_pages: int,
  follow_pages: int,
  asset_probes: int,
  queued_pages: int,
  rows: int,
) -> None:
  if config.progress_interval == 0:
    return
  if network_operations % config.progress_interval != 0:
    return
  _emit_progress(
    progress_fn,
    "progress: "
    f"{listing_pages} listing pages, "
    f"{follow_pages} follow pages, "
    f"{asset_probes} asset probes, "
    f"{queued_pages} queued pages, "
    f"{rows} unique rows",
  )


def crawl_inventory(
  config: InventoryConfig,
  *,
  fetch_html_fn: Callable[[str, float, str], HtmlFetchResult] = fetch_html,
  probe_url_fn: Callable[[str, float, str], ProbeResult] = probe_url,
  progress_fn: Callable[[str], None] | None = None,
) -> InventoryResult:
  rows: dict[str, InventoryRow] = {}
  duplicates_skipped = [0]
  visited_pages: set[str] = set()
  seen_listing_signatures: set[str] = set()
  queue: deque[str] = deque()
  asset_urls: set[str] = set()
  listing_pages_fetched = 0
  follow_pages_fetched = 0
  asset_probes = 0
  network_operations = 0

  _emit_progress(
    progress_fn,
    "starting inventory crawl: "
    f"max listing pages={config.max_pages}, "
    f"max follow pages={config.max_follow_pages if config.max_follow_pages is not None else 'unbounded'}, "
    f"max assets={config.max_assets if config.max_assets is not None else 'unbounded'}",
  )

  for page_number in range(config.max_pages):
    listing_url = build_listing_url(config.base_url, page_number)
    if config.request_delay_seconds:
      time.sleep(config.request_delay_seconds)
    page_result = fetch_html_fn(
      listing_url, config.timeout_seconds, config.user_agent
    )
    listing_pages_fetched += 1
    network_operations += 1
    page_title, links = parse_page(page_result.html)
    page_row = _register_row(
      rows, duplicates_skipped, url=listing_url, title=page_title
    )
    page_row.resource_kind = "listing_page"
    _update_page_row(
      page_row,
      title=page_title,
      content_type=page_result.content_type,
      status=page_result.status,
      linked_documents=0,
    )
    if page_result.status != 200:
      break

    listing_discovered_urls: list[str] = []
    for link in links:
      if not is_relevant_href(listing_url, link.href):
        continue
      absolute = normalize_url(listing_url, link.href)
      if _link_is_dataset_page(listing_url, link.href):
        listing_discovered_urls.append(absolute)
        row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=listing_url,
          source_title=page_title,
        )
        row.resource_kind = "dataset_page"
        if absolute not in visited_pages:
          queue.append(absolute)
      elif _link_is_documentation(listing_url, link.href):
        listing_discovered_urls.append(absolute)
        row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=listing_url,
          source_title=page_title,
        )
        row.resource_kind = "documentation_page"
        if absolute not in visited_pages:
          queue.append(absolute)
      elif _link_is_asset(listing_url, link.href):
        if absolute not in asset_urls and _limit_reached(
          config.max_assets, len(asset_urls)
        ):
          continue
        listing_discovered_urls.append(absolute)
        asset_urls.add(absolute)
        row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=listing_url,
          source_title=page_title,
        )
        row.resource_kind = "asset"
        if _asset_probe_needed(row):
          _probe_asset_row(row, config, probe_url_fn=probe_url_fn)
          asset_probes += 1
          network_operations += 1

    page_row.linked_documents = len(set(listing_discovered_urls))
    _emit_periodic_progress(
      config,
      progress_fn,
      network_operations=network_operations,
      listing_pages=listing_pages_fetched,
      follow_pages=follow_pages_fetched,
      asset_probes=asset_probes,
      queued_pages=len(queue),
      rows=len(rows),
    )
    signature = hashlib.sha1(
      "\n".join(sorted(set(listing_discovered_urls))).encode("utf-8")
    ).hexdigest()
    if page_number > 0 and signature in seen_listing_signatures:
      break
    seen_listing_signatures.add(signature)
    if not listing_discovered_urls and page_number > 0:
      break

  while queue:
    if _limit_reached(config.max_follow_pages, follow_pages_fetched):
      _emit_progress(
        progress_fn,
        f"stopped follow-page crawl at configured limit: {config.max_follow_pages}",
      )
      break
    current_url = queue.popleft()
    if current_url in visited_pages:
      continue
    visited_pages.add(current_url)

    if config.request_delay_seconds:
      time.sleep(config.request_delay_seconds)
    page_result = fetch_html_fn(
      current_url, config.timeout_seconds, config.user_agent
    )
    follow_pages_fetched += 1
    network_operations += 1
    page_title, links = parse_page(page_result.html)
    row = rows.get(current_url)
    if row is None:
      row = _register_row(
        rows, duplicates_skipped, url=current_url, title=page_title
      )
    if row.resource_kind == "other":
      row.resource_kind = classify_resource_kind(current_url)
    _update_page_row(
      row,
      title=page_title,
      content_type=page_result.content_type,
      status=page_result.status,
      linked_documents=0,
    )
    if page_result.status != 200:
      continue

    page_discovered_urls: list[str] = []
    for link in links:
      if not is_relevant_href(current_url, link.href):
        continue
      absolute = normalize_url(current_url, link.href)
      if _link_is_documentation(current_url, link.href):
        page_discovered_urls.append(absolute)
        child_row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=current_url,
          source_title=page_title,
        )
        child_row.resource_kind = "documentation_page"
        if absolute not in visited_pages:
          queue.append(absolute)
      elif _link_is_dataset_page(current_url, link.href):
        page_discovered_urls.append(absolute)
        child_row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=current_url,
          source_title=page_title,
        )
        child_row.resource_kind = "dataset_page"
        if absolute not in visited_pages:
          queue.append(absolute)
      elif _link_is_asset(current_url, link.href):
        if absolute not in asset_urls and _limit_reached(
          config.max_assets, len(asset_urls)
        ):
          continue
        page_discovered_urls.append(absolute)
        asset_urls.add(absolute)
        child_row = _register_row(
          rows,
          duplicates_skipped,
          url=absolute,
          title=link.text,
          source_url=current_url,
          source_title=page_title,
        )
        child_row.resource_kind = "asset"
        if _asset_probe_needed(child_row):
          _probe_asset_row(child_row, config, probe_url_fn=probe_url_fn)
          asset_probes += 1
          network_operations += 1

    row.linked_documents = len(set(page_discovered_urls))
    _emit_periodic_progress(
      config,
      progress_fn,
      network_operations=network_operations,
      listing_pages=listing_pages_fetched,
      follow_pages=follow_pages_fetched,
      asset_probes=asset_probes,
      queued_pages=len(queue),
      rows=len(rows),
    )

  ordered_rows = _sorted_rows(rows)
  dead_links = _count_dead_links(ordered_rows)
  summary = Counter(row.resource_kind for row in ordered_rows)
  summary["total_urls"] = len(ordered_rows)
  summary["dead_links"] = len(dead_links)
  summary["duplicates_skipped"] = duplicates_skipped[0]

  return InventoryResult(
    config=config,
    rows=ordered_rows,
    summary=dict(summary),
    dead_links=dead_links,
    duplicates_skipped=duplicates_skipped[0],
  )


def write_inventory_csv(rows: list[InventoryRow], output_path: Path) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(
      handle,
      fieldnames=INVENTORY_FIELDNAMES,
    )
    writer.writeheader()
    for row in rows:
      writer.writerow(
        {
          "url": row.url,
          "title": row.title,
          "resource_kind": row.resource_kind,
          "asset_kind": row.asset_kind,
          "content_type": row.content_type,
          "http_status": "" if row.http_status is None else row.http_status,
          "link_state": row.link_state,
          "linked_documents": row.linked_documents,
          "source_url": row.source_url,
          "source_title": row.source_title,
        }
      )


def write_workspace_summary(result: InventoryResult) -> Path:
  result.config.workspace_dir.mkdir(parents=True, exist_ok=True)
  summary_path = result.config.workspace_dir / "02_source_inventory.md"
  by_kind = Counter(row.resource_kind for row in result.rows)
  by_asset_kind = Counter(row.asset_kind for row in result.rows if row.asset_kind)
  lines = [
    "# Source Inventory",
    "",
    f"- Base URL: {result.config.base_url}",
    f"- Listing pages crawled: {sum(1 for row in result.rows if row.resource_kind == 'listing_page')}",
    f"- Unique URLs: {len(result.rows)}",
    f"- Dead links: {len(result.dead_links)}",
    f"- Duplicate URLs skipped: {result.duplicates_skipped}",
    "",
    "## By Resource Kind",
    "",
    "| kind | count |",
    "| --- | ---: |",
  ]
  for kind in (
    "listing_page",
    "dataset_page",
    "documentation_page",
    "asset",
    "other",
  ):
    lines.append(f"| {kind} | {by_kind.get(kind, 0)} |")
  lines.extend(["", "## By Asset Kind", "", "| kind | count |", "| --- | ---: |"])
  if by_asset_kind:
    for kind, count in sorted(by_asset_kind.items()):
      lines.append(f"| {kind} | {count} |")
  else:
    lines.append("| none | 0 |")
  lines.extend(["", "## Dead Links", ""])
  if result.dead_links:
    lines.extend(
      ["| url | source | status | content_type |", "| --- | --- | ---: | --- |"]
    )
    for row in result.dead_links[:25]:
      lines.append(
        f"| {row.url} | {row.source_url or ''} | {row.http_status or ''} | {row.content_type or ''} |"
      )
    if len(result.dead_links) > 25:
      lines.append(
        f"\n- Additional dead links omitted: {len(result.dead_links) - 25}"
      )
  else:
    lines.append("- None")
  summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
  return summary_path


def run_inventory(config: InventoryConfig) -> tuple[InventoryResult, Path]:
  result = crawl_inventory(config)
  write_inventory_csv(result.rows, config.output_path)
  summary_path = write_workspace_summary(result)
  return result, summary_path


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Discover and inventory CMS data documentation pages."
  )
  parser.add_argument("--base-url", default="https://resdac.org/cms-data")
  parser.add_argument(
    "--max-pages",
    type=int,
    default=4,
    dest="max_pages",
    help="Maximum ResDAC listing pages to crawl. Follow-up pages are controlled separately.",
  )
  parser.add_argument(
    "--max-listing-pages",
    type=int,
    dest="max_pages",
    help="Alias for --max-pages with clearer naming.",
  )
  parser.add_argument(
    "--max-follow-pages",
    type=int,
    default=None,
    help="Maximum discovered dataset/documentation pages to fetch after listing pages.",
  )
  parser.add_argument(
    "--max-assets",
    type=int,
    default=None,
    help="Maximum unique asset URLs to inventory and probe.",
  )
  parser.add_argument(
    "--output", type=Path, default=Path("manifests/site_inventory.csv")
  )
  parser.add_argument("--workspace-dir", type=Path, default=Path("_workspace"))
  parser.add_argument("--timeout-seconds", type=float, default=20.0)
  parser.add_argument("--request-delay-seconds", type=float, default=0.5)
  parser.add_argument(
    "--progress-interval",
    type=int,
    default=25,
    help="Print progress after this many network operations; use 0 to disable.",
  )
  return parser


def _print_progress(message: str) -> None:
  print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  config = InventoryConfig(
    base_url=args.base_url,
    max_pages=args.max_pages,
    max_follow_pages=args.max_follow_pages,
    max_assets=args.max_assets,
    timeout_seconds=args.timeout_seconds,
    request_delay_seconds=args.request_delay_seconds,
    progress_interval=args.progress_interval,
    output_path=args.output,
    workspace_dir=args.workspace_dir,
  )
  result = crawl_inventory(config, progress_fn=_print_progress)
  write_inventory_csv(result.rows, config.output_path)
  summary_path = write_workspace_summary(result)
  print(
    f"wrote {len(result.rows)} inventory rows to {config.output_path} "
    f"and {summary_path}"
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
