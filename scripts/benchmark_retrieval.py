#!/usr/bin/env python3
"""Benchmark script to compare retrieval times and quality of ResDAC search approaches.

This script compares the legacy in-memory Python BM25 search against the new
SQLite FTS5 retrieval backend, measuring index build time, cold start CLI subprocess latency,
warm query latency, and search relevance quality.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# Add src to python path to allow importing local modules
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cms_kb.retrieval import (  # noqa: E402
  RetrievalConfig,
  SearchResult,
  build_index,
  load_retrievable_records,
  search_records,
  search_records_sqlite,
)

DEFAULT_KEYWORDS = [
  "BENE_ID",
  "medicare advantage",
  "dual eligibility",
  "MBSF",
  "encounter"
]

DELAY_BETWEEN_REQUESTS = 1.0  # Be polite to ResDAC


class ResdacSearchParser(HTMLParser):
  """Parses ResDAC site search node HTML page to extract titles, URLs and snippets."""
  def __init__(self):
    super().__init__()
    self.results: list[dict[str, str]] = []
    self.in_h2 = False
    self.in_a = False
    self.in_snippet = False
    self.temp_title = ""
    self.temp_url = ""
    self.temp_snippet: list[str] = []

  def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
    attrs_dict = dict(attrs)
    if tag == "h2":
      self.in_h2 = True
      self.temp_title = ""
      self.temp_url = ""
    elif tag == "a" and self.in_h2:
      self.in_a = True
      self.temp_url = attrs_dict.get("href", "") or ""
    elif tag == "p" and attrs_dict.get("class") == "search-snippet":
      self.in_snippet = True
      self.temp_snippet = []

  def handle_data(self, data: str):
    if self.in_h2 and self.in_a:
      self.temp_title += data
    elif self.in_snippet:
      self.temp_snippet.append(data)

  def handle_endtag(self, tag: str):
    if tag == "a" and self.in_a:
      self.in_a = False
    elif tag == "h2" and self.in_h2:
      self.in_h2 = False
    elif tag == "p" and self.in_snippet:
      self.in_snippet = False
      snippet_text = "".join(self.temp_snippet).strip()
      if self.temp_title and self.temp_url:
        self.results.append({
          "title": self.temp_title.strip(),
          "url": self.temp_url,
          "snippet": snippet_text
        })
        self.temp_title = ""
        self.temp_url = ""


def load_archive_manifest() -> dict[str, str]:
  """Load the local_path -> original_url mapping from the preservation manifest."""
  manifest_path = ROOT / "manifests/archive_manifest.csv"
  mapping = {}
  if manifest_path.is_file():
    with manifest_path.open("r", encoding="utf-8") as f:
      reader = csv.DictReader(f)
      for row in reader:
        local_path = row.get("local_path", "").strip()
        url = row.get("url", "").strip()
        if local_path and url:
          mapping[local_path] = url
  return mapping


def extract_file_metadata(file_path: Path, query: str, url_mapping: dict[str, str]) -> dict[str, str] | None:
  """Parse matching HTML file to extract title, query-centric snippet, and source URL."""
  try:
    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
      content = f.read()
    
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else file_path.name
    
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    
    query_lower = query.lower()
    idx = text.lower().find(query_lower)
    if idx != -1:
      start = max(0, idx - 40)
      end = min(len(text), idx + 140)
      snippet = text[start:end].strip()
      if start > 0:
        snippet = f"...{snippet}"
      if end < len(text):
        snippet = f"{snippet}..."
    else:
      snippet = text[:180] + "..."
      
    rel_path = str(file_path.relative_to(ROOT)).replace("\\", "/")
    url = url_mapping.get(rel_path, f"file:///{rel_path}")
    
    return {
      "title": title,
      "url": url,
      "snippet": snippet
    }
  except Exception as e:
    print(f"Error parsing file {file_path}: {e}", file=sys.stderr)
    return None


def benchmark_internet(query: str, trials: int) -> float:
  """Measure latency of querying ResDAC online search page + HTML parsing."""
  url = f"https://resdac.org/search/node?keys={urllib.parse.quote(query)}"
  headers = {
    "User-Agent": "Mozilla/5.0 (compatible; cms-kb-benchmark/0.1; +https://github.com/SaehwanPark/resdac-knowledge-base)"
  }
  request = urllib.request.Request(url, headers=headers)
  
  latencies = []
  for trial in range(trials):
    if trial > 0:
      time.sleep(DELAY_BETWEEN_REQUESTS)
    
    start_time = time.perf_counter()
    try:
      with urllib.request.urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8")
      
      parser = ResdacSearchParser()
      parser.feed(html)
      _ = parser.results[:5]
      
      elapsed = time.perf_counter() - start_time
      latencies.append(elapsed)
    except Exception as e:
      print(f"Error checking {url}: {e}", file=sys.stderr)
      return -1.0
      
  return sum(latencies) / len(latencies)


def benchmark_grep(query: str, url_mapping: dict[str, str], trials: int) -> float:
  """Measure latency of local recursive grep + metadata structuring."""
  latencies = []
  for _ in range(trials):
    start_time = time.perf_counter()
    
    cmd = ["grep", "-rn", "-l", "-i", query, "data/raw/html/"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    file_lines = res.stdout.splitlines()
    
    results = []
    for line in file_lines[:5]:
      file_path = ROOT / line.strip()
      if file_path.is_file():
        meta = extract_file_metadata(file_path, query, url_mapping)
        if meta:
          results.append(meta)
          
    elapsed = time.perf_counter() - start_time
    latencies.append(elapsed)
    
  return sum(latencies) / len(latencies)


def compute_stats(latencies: list[float]) -> dict[str, float]:
  """Computes mean, median, and p95 statistics for latencies."""
  if not latencies:
    return {"mean": 0.0, "median": 0.0, "p95": 0.0}
  sorted_l = sorted(latencies)
  n = len(sorted_l)
  mean = sum(sorted_l) / n
  median = sorted_l[n // 2] if n % 2 != 0 else (sorted_l[n // 2 - 1] + sorted_l[n // 2]) / 2.0
  p95_idx = max(0, min(n - 1, int(n * 0.95)))
  p95 = sorted_l[p95_idx]
  return {"mean": mean, "median": median, "p95": p95}


def compute_quality(results: list[SearchResult], expected_ids: list[str]) -> dict[str, float]:
  """Computes recall@5, reciprocal rank, and citation completeness."""
  returned_ids = [r.record_id for r in results]
  top5_ids = returned_ids[:5]
  
  if expected_ids:
    matched = sum(1 for eid in expected_ids if eid in top5_ids)
    recall = matched / len(expected_ids)
  else:
    recall = 1.0
    
  rr = 0.0
  for idx, rid in enumerate(returned_ids):
    if rid in expected_ids:
      rr = 1.0 / (idx + 1)
      break
      
  citations = sum(1 for r in results if r.source_url.strip())
  citation_completeness = citations / len(results) if results else 0.0
  
  return {
    "recall_at_5": recall,
    "reciprocal_rank": rr,
    "citation_completeness": citation_completeness,
  }


def main():
  parser = argparse.ArgumentParser(description="Benchmark retrieval backends.")
  parser.add_argument("--trials", type=int, default=3, help="Number of trials.")
  parser.add_argument("--database-path", type=Path, default=Path("data/index/retrieval.sqlite"), help="Database path.")
  parser.add_argument("--fixture", type=Path, default=None, help="Optional evaluation fixture JSON path.")
  parser.add_argument("--online", action="store_true", help="Enable online Internet and Grep benchmarks.")
  parser.add_argument("--hybrid", action="store_true", help="Enable hybrid search (semantic reranking) in benchmarks.")
  args = parser.parse_args()

  print("Starting ResDAC retrieval benchmarking...", file=sys.stderr)
  
  # Load archive manifest for online Grep fallback comparison
  url_mapping = {}
  if args.online:
    print("Loading archive manifest mapping...", file=sys.stderr)
    url_mapping = load_archive_manifest()
    print(f"Loaded {len(url_mapping)} file mappings", file=sys.stderr)
  
  # 1. Measure Index Build Latency
  print("Measuring Index Build latency...", file=sys.stderr)
  config = RetrievalConfig(database_path=args.database_path)
  build_latencies = []
  for _ in range(args.trials):
    start_build = time.perf_counter()
    build_index(config, build_embeddings=args.hybrid)
    build_latencies.append(time.perf_counter() - start_build)
  build_stats = compute_stats(build_latencies)
  print(f"  Build index time: mean={build_stats['mean']:.4f}s, median={build_stats['median']:.4f}s, p95={build_stats['p95']:.4f}s", file=sys.stderr)

  # Load warm cache records for legacy Python BM25
  print("Loading local KB records into memory for legacy BM25...", file=sys.stderr)
  start_load = time.perf_counter()
  records = load_retrievable_records(config)
  load_time = time.perf_counter() - start_load
  print(f"  Loaded {len(records)} records in {load_time:.4f}s", file=sys.stderr)

  # Determine test cases
  test_cases = []
  if args.fixture and args.fixture.is_file():
    with args.fixture.open("r", encoding="utf-8") as f:
      test_cases = json.load(f)
  else:
    test_cases = [{"query": kw, "expected_ids": [], "description": "Default keyword"} for kw in DEFAULT_KEYWORDS]

  results_output = {
    "meta": {
      "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
      "num_trials": args.trials,
      "kb_records_count": len(records),
      "kb_load_time_seconds": load_time,
      "index_build_stats_seconds": build_stats,
      "hybrid_enabled": args.hybrid,
    },
    "queries": {}
  }

  for case in test_cases:
    query = case["query"]
    expected = case.get("expected_ids", [])
    desc = case.get("description", "")
    print(f"\nBenchmarking query: '{query}' ({desc})", file=sys.stderr)
    
    # Python Cold (Legacy CLI Subprocess)
    cmd_cold_python = ["uv", "run", "cms-kb-search", "--query", query, "--limit", "5", "--legacy", "--json"]
    python_cold_latencies = []
    for _ in range(args.trials):
      start = time.perf_counter()
      subprocess.run(cmd_cold_python, capture_output=True, text=True)
      python_cold_latencies.append(time.perf_counter() - start)
    python_cold_stats = compute_stats(python_cold_latencies)

    # SQLite Cold (SQLite CLI Subprocess)
    cmd_cold_sqlite = ["uv", "run", "cms-kb-search", "--query", query, "--database-path", str(args.database_path), "--limit", "5", "--json"]
    if args.hybrid:
      cmd_cold_sqlite.append("--hybrid")
    sqlite_cold_latencies = []
    for _ in range(args.trials):
      start = time.perf_counter()
      subprocess.run(cmd_cold_sqlite, capture_output=True, text=True)
      sqlite_cold_latencies.append(time.perf_counter() - start)
    sqlite_cold_stats = compute_stats(sqlite_cold_latencies)

    # Python Warm (In-Memory BM25)
    python_warm_latencies = []
    for _ in range(args.trials):
      start = time.perf_counter()
      _ = search_records(query, records, limit=5)
      python_warm_latencies.append(time.perf_counter() - start)
    python_warm_stats = compute_stats(python_warm_latencies)

    # SQLite Warm
    sqlite_warm_latencies = []
    for _ in range(args.trials):
      start = time.perf_counter()
      _ = search_records_sqlite(query, args.database_path, limit=5, hybrid=args.hybrid)
      sqlite_warm_latencies.append(time.perf_counter() - start)
    sqlite_warm_stats = compute_stats(sqlite_warm_latencies)

    # Get results of Warm SQLite for quality metrics
    warm_sqlite_results = search_records_sqlite(query, args.database_path, limit=5, hybrid=args.hybrid)
    quality_metrics = compute_quality(warm_sqlite_results, expected)

    # Optional online comparisons
    t_internet = -1.0
    t_grep = -1.0
    if args.online:
      print("  Running Internet Search...", file=sys.stderr)
      t_internet = benchmark_internet(query, args.trials)
      print("  Running Grep...", file=sys.stderr)
      t_grep = benchmark_grep(query, url_mapping, args.trials)

    results_output["queries"][query] = {
      "python_cold_seconds": python_cold_stats,
      "sqlite_cold_seconds": sqlite_cold_stats,
      "python_warm_seconds": python_warm_stats,
      "sqlite_warm_seconds": sqlite_warm_stats,
      "quality_metrics": quality_metrics,
    }
    if args.online:
      results_output["queries"][query]["internet_seconds"] = t_internet
      results_output["queries"][query]["local_grep_seconds"] = t_grep

    print(f"  Python Warm: mean={python_warm_stats['mean']:.4f}s, median={python_warm_stats['median']:.4f}s, p95={python_warm_stats['p95']:.4f}s", file=sys.stderr)
    print(f"  SQLite Warm: mean={sqlite_warm_stats['mean']:.4f}s, median={sqlite_warm_stats['median']:.4f}s, p95={sqlite_warm_stats['p95']:.4f}s", file=sys.stderr)
    print(f"  Quality: Recall@5={quality_metrics['recall_at_5']:.2%}, Reciprocal Rank={quality_metrics['reciprocal_rank']:.4f}, Citations={quality_metrics['citation_completeness']:.2%}", file=sys.stderr)

  # Save results
  workspace_dir = ROOT / "_workspace"
  workspace_dir.mkdir(exist_ok=True)
  output_file = workspace_dir / "benchmark_results.json"
  
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(results_output, f, indent=2)
    
  print(f"\nBenchmarking completed. Results saved to {output_file}", file=sys.stderr)


if __name__ == "__main__":
  main()
