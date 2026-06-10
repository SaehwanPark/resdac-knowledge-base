from __future__ import annotations

import csv
from pathlib import Path

from cms_kb.inventory import (
  HtmlFetchResult,
  InventoryConfig,
  InventoryRow,
  ProbeResult,
  crawl_inventory,
  normalize_url,
  parse_page,
  write_inventory_csv,
)


def _listing_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return f"<html><head><title>CMS Data</title></head><body><h1>Find the CMS Data File You Need</h1>{links}</body></html>"


def _dataset_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return f"<html><head><title>PDE</title></head><body><h1>PDE</h1>{links}</body></html>"


def _documentation_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return f"<html><head><title>PDE Documentation</title></head><body><h1>View Data Documentation</h1>{links}</body></html>"


def test_parse_page_preserves_all_links() -> None:
  html = _listing_html("/cms-data/files/pde", "/cms-data/files/pde/data-documentation", "/cms-data?page=1")
  title, links = parse_page(html)

  assert title == "CMS Data"
  assert [link.href for link in links] == [
    "/cms-data/files/pde",
    "/cms-data/files/pde/data-documentation",
    "/cms-data?page=1",
  ]


def test_normalize_url_strips_www_and_fragments() -> None:
  assert normalize_url(
    "https://resdac.org/cms-data",
    "https://www.resdac.org/cms-data/files/pde#top",
  ) == "https://resdac.org/cms-data/files/pde"


def test_crawl_inventory_deduplicates_duplicate_links_and_records_dead_assets(tmp_path: Path) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  dataset_url = "https://resdac.org/cms-data/files/pde"
  doc_url = "https://resdac.org/cms-data/files/pde/data-documentation"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"
  xlsx_url = "https://www2.ccwdata.org/documents/10280/19022436/record-layout-pde.xlsx"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html(
        dataset_url.replace("https://resdac.org", ""),
        dataset_url.replace("https://resdac.org", ""),
        doc_url.replace("https://resdac.org", ""),
      ),
    ),
    dataset_url: HtmlFetchResult(
      url=dataset_url,
      status=200,
      content_type="text/html",
      html=_dataset_html(doc_url.replace("https://resdac.org", "")),
    ),
    doc_url: HtmlFetchResult(
      url=doc_url,
      status=200,
      content_type="text/html",
      html=_documentation_html(pdf_url, xlsx_url),
    ),
  }
  probes = {
    pdf_url: ProbeResult(url=pdf_url, status=200, content_type="application/pdf"),
    xlsx_url: ProbeResult(
      url=xlsx_url,
      status=404,
      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
  }

  fetch_calls: list[str] = []
  probe_calls: list[str] = []

  def fake_fetch(url: str, timeout_seconds: float, user_agent: str) -> HtmlFetchResult:
    fetch_calls.append(url)
    return pages[url]

  def fake_probe(url: str, timeout_seconds: float, user_agent: str) -> ProbeResult:
    probe_calls.append(url)
    return probes[url]

  config = InventoryConfig(
    base_url="https://resdac.org/cms-data",
    max_pages=1,
    output_path=tmp_path / "cms-kb-test.csv",
  )
  result = crawl_inventory(config, fetch_html_fn=fake_fetch, probe_url_fn=fake_probe)

  urls = [row.url for row in result.rows]
  assert listing_url in urls
  assert dataset_url in urls
  assert doc_url in urls
  assert pdf_url in urls
  assert xlsx_url in urls
  assert urls.count(dataset_url) == 1
  assert len(fetch_calls) == 3
  assert probe_calls == [pdf_url, xlsx_url]

  dead = {row.url: row for row in result.dead_links}
  assert xlsx_url in dead
  assert dead[xlsx_url].link_state == "dead"
  assert dead[xlsx_url].http_status == 404


def test_crawl_inventory_stops_when_listing_page_repeats(tmp_path: Path) -> None:
  page0 = "https://resdac.org/cms-data?page=0"
  page1 = "https://resdac.org/cms-data?page=1"
  dataset_url = "https://resdac.org/cms-data/files/pde"

  pages = {
    page0: HtmlFetchResult(
      url=page0,
      status=200,
      content_type="text/html",
      html=_listing_html("/cms-data/files/pde"),
    ),
    page1: HtmlFetchResult(
      url=page1,
      status=200,
      content_type="text/html",
      html=_listing_html("/cms-data/files/pde"),
    ),
    dataset_url: HtmlFetchResult(
      url=dataset_url,
      status=200,
      content_type="text/html",
      html=_dataset_html(),
    ),
  }

  fetch_calls: list[str] = []

  def fake_fetch(url: str, timeout_seconds: float, user_agent: str) -> HtmlFetchResult:
    fetch_calls.append(url)
    return pages[url]

  config = InventoryConfig(
    base_url="https://resdac.org/cms-data",
    max_pages=3,
    output_path=tmp_path / "cms-kb-test.csv",
  )
  result = crawl_inventory(
    config,
    fetch_html_fn=fake_fetch,
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(url=url, status=200),
  )

  assert fetch_calls == [page0, page1, dataset_url]
  assert any(row.url == dataset_url for row in result.rows)


def test_write_inventory_csv_creates_expected_columns(tmp_path: Path) -> None:
  output = tmp_path / "site_inventory.csv"
  write_inventory_csv(
    [
      InventoryRow(
        url="https://example.com",
        title="Example",
        resource_kind="listing_page",
        content_type="text/html",
        http_status=200,
        link_state="live",
        linked_documents=1,
      ),
    ],
    output,
  )

  with output.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))

  assert rows[0]["url"] == "https://example.com"
  assert rows[0]["linked_documents"] == "1"
