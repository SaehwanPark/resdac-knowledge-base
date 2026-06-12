from __future__ import annotations

import csv
from pathlib import Path

from cms_kb.inventory import (
  HtmlFetchResult,
  InventoryConfig,
  InventoryRow,
  ProbeResult,
  build_arg_parser,
  crawl_inventory,
  normalize_url,
  parse_page,
  write_workspace_summary,
  write_inventory_csv,
)


def _listing_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return f"<html><head><title>CMS Data</title></head><body><h1>Find the CMS Data File You Need</h1>{links}</body></html>"


def _dataset_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return (
    f"<html><head><title>PDE</title></head><body><h1>PDE</h1>{links}</body></html>"
  )


def _documentation_html(*hrefs: str) -> str:
  links = "".join(f'<a href="{href}">Link</a>' for href in hrefs)
  return f"<html><head><title>PDE Documentation</title></head><body><h1>View Data Documentation</h1>{links}</body></html>"


def test_parse_page_preserves_all_links() -> None:
  html = _listing_html(
    "/cms-data/files/pde",
    "/cms-data/files/pde/data-documentation",
    "/cms-data?page=1",
  )
  title, links = parse_page(html)

  assert title == "CMS Data"
  assert [link.href for link in links] == [
    "/cms-data/files/pde",
    "/cms-data/files/pde/data-documentation",
    "/cms-data?page=1",
  ]


def test_normalize_url_strips_www_and_fragments() -> None:
  assert (
    normalize_url(
      "https://resdac.org/cms-data",
      "https://www.resdac.org/cms-data/files/pde#top",
    )
    == "https://resdac.org/cms-data/files/pde"
  )


def test_arg_parser_accepts_max_listing_pages_alias() -> None:
  args = build_arg_parser().parse_args(["--max-listing-pages", "2"])

  assert args.max_pages == 2


def test_crawl_inventory_deduplicates_duplicate_links_and_records_dead_assets(
  tmp_path: Path,
) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  dataset_url = "https://resdac.org/cms-data/files/pde"
  doc_url = "https://resdac.org/cms-data/files/pde/data-documentation"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"
  xlsx_url = (
    "https://www2.ccwdata.org/documents/10280/19022436/record-layout-pde.xlsx"
  )

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

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
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


def test_crawl_inventory_keeps_transient_page_status_unknown(
  tmp_path: Path,
) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  dataset_url = "https://resdac.org/cms-data/files/pde"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html("/cms-data/files/pde"),
    ),
    dataset_url: HtmlFetchResult(
      url=dataset_url,
      status=429,
      content_type="text/html",
      html="",
    ),
  }

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
    return pages[url]

  result = crawl_inventory(
    InventoryConfig(
      base_url="https://resdac.org/cms-data",
      max_pages=1,
      output_path=tmp_path / "cms-kb-test.csv",
    ),
    fetch_html_fn=fake_fetch,
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(
      url=url, status=200
    ),
  )

  row = next(row for row in result.rows if row.url == dataset_url)
  assert row.http_status == 429
  assert row.link_state == "unknown"
  assert result.dead_links == []
  assert result.summary["transient_links"] == 1


def test_crawl_inventory_keeps_transient_asset_probe_status_unknown(
  tmp_path: Path,
) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"

  result = crawl_inventory(
    InventoryConfig(
      base_url="https://resdac.org/cms-data",
      max_pages=1,
      output_path=tmp_path / "cms-kb-test.csv",
    ),
    fetch_html_fn=lambda url, timeout_seconds, user_agent: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html(pdf_url),
    ),
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(
      url=url, status=503, content_type="application/pdf"
    ),
  )

  row = next(row for row in result.rows if row.url == pdf_url)
  assert row.http_status == 503
  assert row.link_state == "unknown"
  assert row.asset_kind == "pdf"
  assert result.dead_links == []
  assert result.summary["transient_links"] == 1


def test_write_workspace_summary_lists_transient_unresolved_links(
  tmp_path: Path,
) -> None:
  result = crawl_inventory(
    InventoryConfig(
      base_url="https://resdac.org/cms-data",
      max_pages=1,
      output_path=tmp_path / "cms-kb-test.csv",
      workspace_dir=tmp_path / "_workspace",
    ),
    fetch_html_fn=lambda url, timeout_seconds, user_agent: HtmlFetchResult(
      url="https://resdac.org/cms-data?page=0",
      status=429,
      content_type="text/html",
      html="",
    ),
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(
      url=url, status=200
    ),
  )

  summary_path = write_workspace_summary(result)

  summary = summary_path.read_text(encoding="utf-8")
  assert "- Dead links: 0" in summary
  assert "- Transient unresolved links: 1" in summary
  assert "## Transient Unresolved Links" in summary
  assert "https://resdac.org/cms-data?page=0" in summary


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

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
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
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(
      url=url, status=200
    ),
  )

  assert fetch_calls == [page0, page1, dataset_url]
  assert any(row.url == dataset_url for row in result.rows)


def test_crawl_inventory_probes_assets_linked_from_listing_page(
  tmp_path: Path,
) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html(pdf_url),
    ),
  }
  probes = {
    pdf_url: ProbeResult(url=pdf_url, status=200, content_type="application/pdf"),
  }
  probe_calls: list[str] = []

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
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

  asset = next(row for row in result.rows if row.url == pdf_url)
  assert probe_calls == [pdf_url]
  assert asset.link_state == "live"
  assert asset.http_status == 200
  assert asset.asset_kind == "pdf"


def test_crawl_inventory_can_skip_follow_pages_with_limit(tmp_path: Path) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  dataset_url = "https://resdac.org/cms-data/files/pde"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html("/cms-data/files/pde"),
    ),
  }
  fetch_calls: list[str] = []
  progress_messages: list[str] = []

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
    fetch_calls.append(url)
    return pages[url]

  config = InventoryConfig(
    base_url="https://resdac.org/cms-data",
    max_pages=1,
    max_follow_pages=0,
    output_path=tmp_path / "cms-kb-test.csv",
  )
  result = crawl_inventory(
    config,
    fetch_html_fn=fake_fetch,
    probe_url_fn=lambda url, timeout_seconds, user_agent: ProbeResult(
      url=url, status=200
    ),
    progress_fn=progress_messages.append,
  )

  assert fetch_calls == [listing_url]
  assert any(row.url == dataset_url for row in result.rows)
  assert any("configured limit" in message for message in progress_messages)


def test_crawl_inventory_deduplicates_asset_probes(tmp_path: Path) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  doc_url = "https://resdac.org/cms-data/files/pde/data-documentation"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html(doc_url.replace("https://resdac.org", "")),
    ),
    doc_url: HtmlFetchResult(
      url=doc_url,
      status=200,
      content_type="text/html",
      html=_documentation_html(pdf_url, pdf_url),
    ),
  }
  probe_calls: list[str] = []

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
    return pages[url]

  def fake_probe(url: str, timeout_seconds: float, user_agent: str) -> ProbeResult:
    probe_calls.append(url)
    return ProbeResult(url=url, status=200, content_type="application/pdf")

  config = InventoryConfig(
    base_url="https://resdac.org/cms-data",
    max_pages=1,
    output_path=tmp_path / "cms-kb-test.csv",
  )
  result = crawl_inventory(config, fetch_html_fn=fake_fetch, probe_url_fn=fake_probe)

  assert probe_calls == [pdf_url]
  assert [row.url for row in result.rows].count(pdf_url) == 1


def test_crawl_inventory_honors_asset_limit(tmp_path: Path) -> None:
  listing_url = "https://resdac.org/cms-data?page=0"
  pdf_url = "https://www2.ccwdata.org/documents/10280/19022436/codebook-pde.pdf"

  pages = {
    listing_url: HtmlFetchResult(
      url=listing_url,
      status=200,
      content_type="text/html",
      html=_listing_html(pdf_url),
    ),
  }
  probe_calls: list[str] = []

  def fake_fetch(
    url: str, timeout_seconds: float, user_agent: str
  ) -> HtmlFetchResult:
    return pages[url]

  def fake_probe(url: str, timeout_seconds: float, user_agent: str) -> ProbeResult:
    probe_calls.append(url)
    return ProbeResult(url=url, status=200, content_type="application/pdf")

  config = InventoryConfig(
    base_url="https://resdac.org/cms-data",
    max_pages=1,
    max_assets=0,
    output_path=tmp_path / "cms-kb-test.csv",
  )
  result = crawl_inventory(config, fetch_html_fn=fake_fetch, probe_url_fn=fake_probe)

  assert probe_calls == []
  assert all(row.url != pdf_url for row in result.rows)


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
