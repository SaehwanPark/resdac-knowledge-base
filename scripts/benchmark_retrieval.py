#!/usr/bin/env python3
"""Benchmark script to compare retrieval times of ResDAC search approaches.

This script ensures a fair comparison: all three search approaches construct
the same JSON knowledge metadata structure containing the result title, source url, and snippet.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# Add src to python path to allow importing local modules
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cms_kb.retrieval import (  # noqa: E402
  RetrievableRecord,
  RetrievalConfig,
  load_retrievable_records,
  search_records,
)

KEYWORDS = [
  "BENE_ID",
  "medicare advantage",
  "dual eligibility",
  "MBSF",
  "encounter"
]

NUM_TRIALS = 3
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
    
    # Extract title
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else file_path.name
    
    # Clean text to extract query-centric snippet
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    
    # Find match and slice snippet
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
      
    # Lookup URL from manifest mapping
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

def benchmark_internet(query: str) -> float:
  """Measure latency of querying ResDAC online search page + HTML parsing to JSON."""
  url = f"https://resdac.org/search/node?keys={urllib.parse.quote(query)}"
  headers = {
    "User-Agent": "Mozilla/5.0 (compatible; cms-kb-benchmark/0.1; +https://github.com/SaehwanPark/resdac-knowledge-base)"
  }
  request = urllib.request.Request(url, headers=headers)
  
  latencies = []
  for trial in range(NUM_TRIALS):
    if trial > 0:
      time.sleep(DELAY_BETWEEN_REQUESTS)
    
    start_time = time.perf_counter()
    try:
      with urllib.request.urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8")
      
      # Parse HTML to complete the JSON knowledge metadata complexity
      parser = ResdacSearchParser()
      parser.feed(html)
      _ = parser.results[:5]
      
      elapsed = time.perf_counter() - start_time
      latencies.append(elapsed)
    except Exception as e:
      print(f"Error checking {url}: {e}", file=sys.stderr)
      return -1.0
      
  return sum(latencies) / len(latencies)

def benchmark_grep(query: str, url_mapping: dict[str, str]) -> float:
  """Measure latency of local recursive grep + metadata structuring."""
  latencies = []
  for _ in range(NUM_TRIALS):
    start_time = time.perf_counter()
    
    # Run grep to get list of matching files
    cmd = ["grep", "-rn", "-l", "-i", query, "data/raw/html/"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    file_lines = res.stdout.splitlines()
    
    # Process top 5 matching files to build identical JSON metadata
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

def benchmark_rkb_cold(query: str) -> float:
  """Measure latency of cold-starting RKB search via CLI subprocess + JSON formatting."""
  cmd = ["uv", "run", "cms-kb-search", "--query", query, "--limit", "5", "--json"]
  
  latencies = []
  for _ in range(NUM_TRIALS):
    start_time = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    # Parse CLI json output and format to unified metadata structure
    results = json.loads(res.stdout)
    formatted = []
    for r in results:
      formatted.append({
        "title": r.get("title", ""),
        "url": r.get("source_url", ""),
        "snippet": r.get("snippet", "")
      })
      
    elapsed = time.perf_counter() - start_time
    latencies.append(elapsed)
    
  return sum(latencies) / len(latencies)

def benchmark_rkb_warm(
  query: str,
  records: list[RetrievableRecord],
  config: RetrievalConfig,
) -> float:
  """Measure latency of warm in-memory RKB BM25 search + JSON formatting."""
  latencies = []
  for _ in range(NUM_TRIALS):
    start_time = time.perf_counter()
    results = search_records(query, records, limit=5)
    formatted = []
    for r in results:
      formatted.append({
        "title": r.title,
        "url": r.source_url,
        "snippet": r.snippet
      })
      
    elapsed = time.perf_counter() - start_time
    latencies.append(elapsed)
    
  return sum(latencies) / len(latencies)

def main():
  print("Starting ResDAC fair retrieval benchmarking...", file=sys.stderr)
  
  # Load local file to URL mapping for Grep benchmark
  print("Loading archive manifest mapping...", file=sys.stderr)
  url_mapping = load_archive_manifest()
  print(f"Loaded {len(url_mapping)} file mappings", file=sys.stderr)
  
  # Load in-memory records once for the warm benchmark
  print("Loading local KB records into memory for warm benchmark...", file=sys.stderr)
  start_load = time.perf_counter()
  config = RetrievalConfig()
  records = load_retrievable_records(config)
  load_time = time.perf_counter() - start_load
  print(f"Loaded {len(records)} records in {load_time:.4f}s", file=sys.stderr)

  results = {
    "meta": {
      "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
      "num_trials": NUM_TRIALS,
      "kb_records_count": len(records),
      "kb_load_time_seconds": load_time
    },
    "queries": {}
  }

  for query in KEYWORDS:
    print(f"\nBenchmarking query: '{query}'", file=sys.stderr)
    
    # 1. Internet only (with search parsing)
    print("  Running Internet Search (with HTML parsing)...", file=sys.stderr)
    t_internet = benchmark_internet(query)
    print(f"    Avg Time: {t_internet:.4f}s", file=sys.stderr)
    
    # 2. Local raw-data grep (with file parsing & mapping)
    print("  Running Local Raw Grep (with file metadata construction)...", file=sys.stderr)
    t_grep = benchmark_grep(query, url_mapping)
    print(f"    Avg Time: {t_grep:.4f}s", file=sys.stderr)
    
    # 3. RKB Cold (with subprocess + format mapping)
    print("  Running RKB (Cold CLI subprocess)...", file=sys.stderr)
    t_rkb_cold = benchmark_rkb_cold(query)
    print(f"    Avg Time: {t_rkb_cold:.4f}s", file=sys.stderr)
    
    # 4. RKB Warm (with formatting mapping)
    print("  Running RKB (Warm In-Memory)...", file=sys.stderr)
    t_rkb_warm = benchmark_rkb_warm(query, records, config)
    print(f"    Avg Time: {t_rkb_warm:.4f}s", file=sys.stderr)
      
    results["queries"][query] = {
      "internet_seconds": t_internet,
      "local_grep_seconds": t_grep,
      "rkb_cold_seconds": t_rkb_cold,
      "rkb_warm_seconds": t_rkb_warm
    }

  # Save results
  workspace_dir = ROOT / "_workspace"
  workspace_dir.mkdir(exist_ok=True)
  output_file = workspace_dir / "benchmark_results.json"
  
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
    
  print(f"\nBenchmarking completed. Results saved to {output_file}", file=sys.stderr)
  
if __name__ == "__main__":
  main()
