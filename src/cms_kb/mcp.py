"""Model Context Protocol (MCP) server for CMS KB retrieval and agent context.

This module implements an MCP server using FastMCP. It exposes tool wrappers
allowing external LLM agents and clients to query the local CMS Knowledge Base
interactively. The tools provide search capabilities over datasets, documents,
variables, and parsed text chunks, including citation-preserving context hits.

Architecture & State Management:
- The `ServerState` object acts as an in-memory database cache. Since loading
  thousands of records from CSV/JSONL files on every query would be slow,
  `ServerState` caches the parsed metadata list and the archive document mappings.
- Setting any configuration path invalidates the cache dynamically.
- Execution runs on the `stdio` transport layer, enabling easy integration with
  MCP-compliant host applications.
"""

from __future__ import annotations

import argparse
import datetime
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from mcp.server.fastmcp import FastMCP

from .agent_api import (
  AgentContextResponse,
  context_hit_from_search_result,
  read_archived_document_map,
)
from .paths import get_packaged_data_path
from .retrieval import (
  RetrievableRecord,
  RetrievalConfig,
  load_retrievable_records,
  run_retrieval,
)



class ServerState:
  """Caches and manages the in-memory metadata state for the MCP server.

  This avoids expensive re-reads of the CSV and JSONL source files on
  each tool invocation. Modifying configurations invalidates cached objects.
  """

  def __init__(self) -> None:
    self._config = RetrievalConfig()
    self._archive_manifest_path = Path("manifests/archive_manifest.csv")
    self.default_limit: int = 5
    self._records: list[RetrievableRecord] | None = None
    self._archived_documents_by_url: dict[str, str] | None = None

  @property
  def config(self) -> RetrievalConfig:
    """The search and index configuration settings."""
    return self._config

  @config.setter
  def config(self, value: RetrievalConfig) -> None:
    self._config = value
    # Invalidate cached records so that they are reloaded with the new configuration
    self._records = None

  def get_records(self) -> list[RetrievableRecord]:
    """Retrieves all indexed metadata records, loading them on-demand if not cached."""
    if self._records is None:
      self._records = load_retrievable_records(self._config)
    return self._records

  @property
  def archive_manifest_path(self) -> Path:
    """The path to the local archive manifest CSV."""
    return self._archive_manifest_path

  @archive_manifest_path.setter
  def archive_manifest_path(self, value: Path) -> None:
    self._archive_manifest_path = value
    # Invalidate cached archive map when the manifest path changes
    self._archived_documents_by_url = None

  def get_archived_documents_by_url(self) -> dict[str, str]:
    """Loads and caches the URL-to-local-path map for offline citation resolution."""
    if self._archived_documents_by_url is None:
      self._archived_documents_by_url = read_archived_document_map(
        self._archive_manifest_path
      )
    return self._archived_documents_by_url


state = ServerState()
mcp = FastMCP("CMS KB Server")


@mcp.tool()
def search_datasets(query: str, limit: int | None = None) -> str:
  """Search dataset records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="dataset")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_documents(query: str, limit: int | None = None) -> str:
  """Search document records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="document")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_variables(query: str, limit: int | None = None) -> str:
  """Search variable records in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="variable")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def search_chunks(query: str, limit: int | None = None) -> str:
  """Search parsed text chunks in the CMS knowledge base.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit, record_type="chunk")
  return json.dumps([res.model_dump() for res in results], indent=2)


@mcp.tool()
def get_agent_context(query: str, limit: int | None = None) -> str:
  """Get citation-preserving agent context hits for a search query.

  Args:
    query: The search term or query.
    limit: The maximum number of results to return.
  """
  resolved_limit = limit if limit is not None else state.default_limit
  results = run_retrieval(state.config, query, resolved_limit)
  archived_documents_by_url = state.get_archived_documents_by_url()
  hits = [
    context_hit_from_search_result(res, archived_documents_by_url)
    for res in results
  ]
  response = AgentContextResponse(query=query, results=hits)
  return json.dumps(response.model_dump(), indent=2)


def is_process_running(pid: int) -> bool:
  """Checks if a process with the given PID is currently running."""
  if pid <= 0:
    return False
  try:
    os.kill(pid, 0)
  except OSError as err:
    return err.errno == errno.EPERM
  return True


def is_mcp_server_process(pid: int) -> bool:
  """Checks if the given PID is running and corresponds to our MCP server."""
  if not is_process_running(pid):
    return False
  try:
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if cmdline_path.is_file():
      cmdline = cmdline_path.read_text(encoding="utf-8", errors="ignore").replace("\x00", " ")
      return "cms_kb" in cmdline or "cms-kb-mcp" in cmdline
  except Exception:
    # Fallback to general process existence if /proc is not accessible
    pass
  return True


def handle_stop() -> int:
  """Gracefully terminates the background MCP server process."""
  state_file = Path("_workspace/mcp_server_state.json")
  if not state_file.is_file():
    print("Error: No MCP server is currently running.", file=sys.stderr)
    return 1

  try:
    with open(state_file, "r", encoding="utf-8") as f:
      state_data = json.load(f)
    pid = state_data["pid"]
  except Exception as exc:
    print(f"Error reading state file: {exc}. Cleaning up state file.", file=sys.stderr)
    try:
      state_file.unlink(missing_ok=True)
    except Exception:
      pass
    return 1

  if not is_mcp_server_process(pid):
    print(f"MCP server process (PID {pid}) is not running. Cleaning up stale state file.")
    try:
      state_file.unlink(missing_ok=True)
    except Exception:
      pass
    return 0

  print(f"Stopping MCP server (PID: {pid})...")
  try:
    os.kill(pid, signal.SIGTERM)
  except OSError as err:
    print(f"Failed to send SIGTERM to process: {err}", file=sys.stderr)
    return 1

  # Wait for it to stop
  for _ in range(50):  # 5 seconds max
    time.sleep(0.1)
    if not is_process_running(pid):
      break
  else:
    print("Process did not exit, sending SIGKILL...")
    try:
      os.kill(pid, signal.SIGKILL)
    except OSError:
      pass

  try:
    state_file.unlink(missing_ok=True)
  except Exception:
    pass

  print("MCP server stopped successfully.")
  return 0


def handle_status() -> int:
  """Checks and displays the status of the background MCP server."""
  state_file = Path("_workspace/mcp_server_state.json")
  if not state_file.is_file():
    print("MCP server status: stopped")
    return 0

  try:
    with open(state_file, "r", encoding="utf-8") as f:
      state_data = json.load(f)
    pid = state_data["pid"]
    transport = state_data.get("transport", "unknown")
    host = state_data.get("host", "unknown")
    port = state_data.get("port", "unknown")
    start_time = state_data.get("start_time", "unknown")
  except Exception as exc:
    print(f"Error reading state file: {exc}.", file=sys.stderr)
    return 1

  if not is_mcp_server_process(pid):
    print(f"MCP server status: stopped (stale state file found, PID {pid} not running)")
    try:
      state_file.unlink(missing_ok=True)
    except Exception:
      pass
    return 0

  print("MCP server status: running")
  print(f"  PID: {pid}")
  print(f"  Transport: {transport}")
  if transport in ("sse", "streamable-http"):
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    if transport == "sse":
      print(f"  Endpoint: http://{host}:{port}/sse")
  print(f"  Started: {start_time}")
  print("  Log file: _workspace/mcp_server.log")
  return 0


def handle_start(args: argparse.Namespace, argv: list[str]) -> int:
  """Spawns the MCP server in the background as a daemon process."""
  state_file = Path("_workspace/mcp_server_state.json")
  if state_file.is_file():
    try:
      with open(state_file, "r", encoding="utf-8") as f:
        state_data = json.load(f)
      pid = state_data["pid"]
      if is_mcp_server_process(pid):
        print(f"MCP server is already running (PID: {pid}).")
        return 0
    except Exception:
      # Corrupted/invalid json - proceed to start a new server and overwrite
      pass

  # Default to 'sse' transport for background operation
  transport = args.transport or "sse"
  host = args.host
  port = args.port

  workspace_dir = Path("_workspace")
  workspace_dir.mkdir(parents=True, exist_ok=True)
  log_file_path = workspace_dir / "mcp_server.log"

  # Invoke python -m cms_kb.mcp in the foreground for the daemon
  cmd = [sys.executable, "-m", "cms_kb.mcp"]

  # Pass specified parameters
  cmd.extend(["--transport", transport])
  cmd.extend(["--host", host])
  cmd.extend(["--port", str(port)])

  if args.datasets_metadata:
    cmd.extend(["--datasets-metadata", str(args.datasets_metadata)])
  if args.documents_metadata:
    cmd.extend(["--documents-metadata", str(args.documents_metadata)])
  if args.variables_metadata:
    cmd.extend(["--variables-metadata", str(args.variables_metadata)])
  if args.chunks_jsonl:
    cmd.extend(["--chunks-jsonl", str(args.chunks_jsonl)])
  if args.archive_manifest:
    cmd.extend(["--archive-manifest", str(args.archive_manifest)])
  if args.database_path:
    cmd.extend(["--database-path", str(args.database_path)])
  if args.limit:
    cmd.extend(["--limit", str(args.limit)])

  print(f"Starting MCP server in background with transport '{transport}'...")
  if transport in ("sse", "streamable-http"):
    print(f"  Binding to {host}:{port}")

  try:
    log_file = open(log_file_path, "w", encoding="utf-8")
  except Exception as exc:
    print(f"Error: Failed to open log file {log_file_path}: {exc}", file=sys.stderr)
    return 1

  try:
    proc = subprocess.Popen(
      cmd,
      stdout=log_file,
      stderr=subprocess.STDOUT,
      stdin=subprocess.DEVNULL,
      start_new_session=True,
    )
  except Exception as exc:
    print(f"Error spawning background process: {exc}", file=sys.stderr)
    log_file.close()
    return 1

  # Wait a brief moment to check if process is running
  time.sleep(1.0)
  poll_val = proc.poll()
  if poll_val is not None:
    print(f"Error: MCP server failed to start (exit code {poll_val}). Check log file: {log_file_path}", file=sys.stderr)
    log_file.close()
    try:
      with open(log_file_path, "r", encoding="utf-8") as lf:
        lines = lf.readlines()
        print("\nLast log entries:", file=sys.stderr)
        for line in lines[-15:]:
          print(f"  {line.rstrip()}", file=sys.stderr)
    except Exception:
      pass
    return 1

  # Process running successfully, write state
  state_data = {
    "pid": proc.pid,
    "transport": transport,
    "host": host,
    "port": port,
    "start_time": datetime.datetime.now().isoformat(),
  }

  try:
    with open(state_file, "w", encoding="utf-8") as f:
      json.dump(state_data, f, indent=2)
  except Exception as exc:
    print(f"Warning: Failed to write state file: {exc}", file=sys.stderr)

  print(f"MCP server started successfully (PID: {proc.pid}).")
  print(f"Log output redirected to {log_file_path}")
  return 0


def build_arg_parser() -> argparse.ArgumentParser:
  """Constructs the argument parser for starting the MCP server CLI.

  Returns:
    An ArgumentParser instance configured with path and limit defaults.
  """
  parser = argparse.ArgumentParser(
    description="Start the read-only MCP server for CMS KB retrieval."
  )
  parser.add_argument(
    "command",
    nargs="?",
    choices=["start", "stop", "status"],
    help="Action to perform: start, stop, or status (default: run in foreground)",
  )
  parser.add_argument(
    "--datasets-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/datasets.csv"),
  )
  parser.add_argument(
    "--documents-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/documents.csv"),
  )
  parser.add_argument(
    "--variables-metadata",
    type=Path,
    default=get_packaged_data_path("metadata/variables.csv"),
  )
  parser.add_argument(
    "--chunks-jsonl",
    type=Path,
    default=get_packaged_data_path("parsed/chunks.jsonl"),
  )
  parser.add_argument(
    "--archive-manifest",
    type=Path,
    default=Path("manifests/archive_manifest.csv"),
  )
  parser.add_argument(
    "--database-path",
    type=Path,
    default=get_packaged_data_path("index/retrieval.sqlite"),
  )
  parser.add_argument("--limit", type=int, default=5)
  parser.add_argument(
    "--host",
    type=str,
    default="127.0.0.1",
    help="Host to bind the SSE server to (default: 127.0.0.1)",
  )
  parser.add_argument(
    "--port",
    type=int,
    default=8000,
    help="Port to bind the SSE server to (default: 8000)",
  )
  parser.add_argument(
    "--transport",
    type=str,
    choices=["stdio", "sse", "streamable-http"],
    default=None,
    help="Transport protocol to use (default: stdio for foreground, sse for background)",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  """CLI execution entrypoint to configure and start the MCP server.

  Args:
    argv: Command line arguments. Uses sys.argv if None.

  Returns:
    Exit code: 0 for clean execution, 1 on initialization/runtime errors.
  """
  parser = build_arg_parser()
  args = parser.parse_args(argv)

  if args.command == "stop":
    return handle_stop()
  elif args.command == "status":
    return handle_status()
  elif args.command == "start":
    actual_argv = sys.argv[1:] if argv is None else argv
    return handle_start(args, actual_argv)

  if not args.datasets_metadata.is_file():
    print(f"Error: Datasets metadata file not found at {args.datasets_metadata}", file=sys.stderr)
    return 1
  if not args.documents_metadata.is_file():
    print(f"Error: Documents metadata file not found at {args.documents_metadata}", file=sys.stderr)
    return 1

  # Initialize state values with command line overrides
  state.config = RetrievalConfig(
    datasets_metadata_path=args.datasets_metadata,
    documents_metadata_path=args.documents_metadata,
    variables_metadata_path=args.variables_metadata,
    chunks_jsonl_path=args.chunks_jsonl,
    database_path=args.database_path,
  )
  state.archive_manifest_path = args.archive_manifest
  state.default_limit = args.limit

  transport = args.transport or "stdio"
  mcp.settings.host = args.host
  mcp.settings.port = args.port

  try:
    mcp.run(transport)
  except Exception as exc:
    print(f"Error running MCP server: {exc}", file=sys.stderr)
    return 1

  return 0


if __name__ == "__main__":
  sys.exit(main())
