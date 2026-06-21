"""Setup helper command for Model Context Protocol (MCP) clients.

This module provides a CLI wizard to automatically discover and configure
MCP clients (such as Claude Desktop, Claude Code, Antigravity, and Codex)
to run the CMS Knowledge Base MCP server in standard I/O mode.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Client choices mapping CLI key -> human readable name
CLIENT_CHOICES = {
  "claude-desktop": "Claude Desktop",
  "claude-code-project": "Claude Code (Project-level .mcp.json)",
  "claude-code-user": "Claude Code (User-level ~/.claude.json)",
  "antigravity": "Google Antigravity (~/.gemini/antigravity-cli/mcp_config.json)",
  "codex-project": "Codex (Project-level .codex/config.toml)",
  "codex-user": "Codex (User-level ~/.codex/config.toml)",
}


def get_default_config_path(client: str, project_root: Path) -> Path | None:
  """Resolves the default configuration file path for a client based on the OS."""
  home = Path.home()

  if client == "claude-desktop":
    if sys.platform == "win32":
      appdata = os.environ.get("APPDATA")
      if appdata:
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
      return home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
      return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:  # Linux and others
      return home / ".config" / "Claude" / "claude_desktop_config.json"

  elif client == "claude-code-project":
    return project_root / ".mcp.json"

  elif client == "claude-code-user":
    return home / ".claude.json"

  elif client == "antigravity":
    return home / ".gemini" / "antigravity-cli" / "mcp_config.json"

  elif client == "codex-project":
    return project_root / ".codex" / "config.toml"

  elif client == "codex-user":
    return home / ".codex" / "config.toml"

  return None


def detect_project_root() -> Path:
  """Detects the absolute path to the project root directory.

  Uses the location of this file in the `src/cms_kb` directory.
  """
  # This file is src/cms_kb/mcp_setup.py.
  # Parent 1: src/cms_kb
  # Parent 2: src
  # Parent 3: project root
  try:
    return Path(__file__).resolve().parents[2]
  except Exception:
    return Path.cwd().resolve()


def update_json_config(
  path: Path,
  server_name: str,
  command: str,
  args: list[str],
  dry_run: bool = False,
) -> tuple[bool, str]:
  """Safely updates a JSON configuration file with the MCP server command/args.

  Maintains existing JSON keys and handles formatting and file creation.
  """
  new_entry = {
    "command": command,
    "args": args,
  }

  content: dict[str, Any] = {}

  if path.is_file():
    try:
      with open(path, "r", encoding="utf-8") as f:
        file_text = f.read().strip()
        if file_text:
          content = json.loads(file_text)
    except json.JSONDecodeError as exc:
      return False, f"Existing configuration at {path} contains invalid JSON: {exc}"
    except Exception as exc:
      return False, f"Failed to read configuration at {path}: {exc}"

  if not isinstance(content, dict):
    return False, f"Existing JSON root at {path} is not an object/dict."

  if "mcpServers" not in content:
    content["mcpServers"] = {}

  if not isinstance(content["mcpServers"], dict):
    return False, f"Existing 'mcpServers' key in {path} is not an object/dict."

  # Check if config is already up to date to prevent churn
  existing_entry = content["mcpServers"].get(server_name)
  if isinstance(existing_entry, dict):
    if (
      existing_entry.get("command") == command
      and existing_entry.get("args") == args
    ):
      return True, f"Already configured and up-to-date in {path}."

  content["mcpServers"][server_name] = new_entry

  if dry_run:
    return True, f"[DRY-RUN] Proposed update for {path}:\n{json.dumps(content, indent=2)}"

  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
      json.dump(content, f, indent=2)
    return True, f"Successfully configured MCP server in {path}."
  except Exception as exc:
    return False, f"Failed to write configuration to {path}: {exc}"


def update_toml_string(
  content: str,
  server_name: str,
  command: str,
  args: list[str],
) -> str:
  """Updates or appends an MCP server TOML section in the configuration string."""
  args_toml = ", ".join(f'"{a}"' for a in args)
  new_section = (
    f"[mcp_servers.{server_name}]\n"
    f'type = "stdio"\n'
    f'command = "{command}"\n'
    f'args = [{args_toml}]\n'
  )

  pattern = rf"(?m)^\s*\[\s*mcp_servers\.{re.escape(server_name)}\s*\]\s*\n"
  match = re.search(pattern, content)
  if match:
    start_idx = match.start()
    next_section = re.search(r"(?m)^\s*\[", content[match.end() :])
    if next_section:
      end_idx = match.end() + next_section.start()
    else:
      end_idx = len(content)
    updated = content[:start_idx] + new_section + content[end_idx:]
    return updated
  else:
    # Append
    if content and not content.endswith("\n"):
      content += "\n"
    # Ensure there is a gap line
    if content and not content.endswith("\n\n"):
      content += "\n"
    content += new_section
    return content


def update_toml_config(
  path: Path,
  server_name: str,
  command: str,
  args: list[str],
  dry_run: bool = False,
) -> tuple[bool, str]:
  """Safely updates a TOML configuration file for Codex.

  Avoids parsing errors and preserves existing settings.
  """
  content = ""
  if path.is_file():
    try:
      with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    except Exception as exc:
      return False, f"Failed to read TOML configuration at {path}: {exc}"

  # Check if already present and identical to avoid churn
  args_toml = ", ".join(f'"{a}"' for a in args)
  expected_lines = [
    f"[mcp_servers.{server_name}]",
    'type = "stdio"',
    f'command = "{command}"',
    f"args = [{args_toml}]",
  ]
  if all(line in content for line in expected_lines):
    return True, f"Already configured and up-to-date in {path}."

  updated_content = update_toml_string(content, server_name, command, args)

  if dry_run:
    return True, f"[DRY-RUN] Proposed update for {path}:\n{updated_content}"

  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
      f.write(updated_content)
    return True, f"Successfully configured MCP server in {path}."
  except Exception as exc:
    return False, f"Failed to write configuration to {path}: {exc}"


def build_arg_parser() -> argparse.ArgumentParser:
  """Constructs the CLI argument parser for MCP setup."""
  parser = argparse.ArgumentParser(
    description="Configure Model Context Protocol (MCP) clients for CMS Knowledge Base."
  )
  parser.add_argument(
    "--client",
    action="append",
    choices=list(CLIENT_CHOICES.keys()) + ["all"],
    help="One or more clients to configure (can specify multiple). Use 'all' to select all supported clients.",
  )
  parser.add_argument(
    "--project-path",
    type=Path,
    help="Explicit absolute path to the project root directory. Defaults to auto-detected path.",
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Print the planned modifications without writing changes to disk.",
  )
  parser.add_argument(
    "--force",
    "-y",
    action="store_true",
    help="Overwrite or create configuration files without interactive confirmation prompts.",
  )
  return parser


def run_interactive_wizard() -> list[str]:
  """Runs the interactive console setup wizard to select clients."""
  print("=== CMS Knowledge Base MCP Client Setup ===")
  print("Select one or more clients to configure (e.g. '1,4' or '7'):\n")

  choices_keys = list(CLIENT_CHOICES.keys())
  for idx, label in enumerate(choices_keys, 1):
    print(f"  {idx}) {CLIENT_CHOICES[label]}")
  print(f"  {len(choices_keys) + 1}) All of the above")
  print(f"  {len(choices_keys) + 2}) Exit")

  try:
    selection = input("\nSelect options: ").strip()
  except (KeyboardInterrupt, EOFError):
    print("\nSetup cancelled.")
    sys.exit(0)

  if not selection:
    print("No options selected. Exiting.")
    return []

  selected_indices: list[int] = []
  for part in selection.split(","):
    part = part.strip()
    if not part:
      continue
    try:
      val = int(part)
      selected_indices.append(val)
    except ValueError:
      print(f"Warning: Invalid option '{part}' skipped.")

  if len(choices_keys) + 2 in selected_indices:
    print("Exiting.")
    return []

  if len(choices_keys) + 1 in selected_indices:
    return choices_keys

  clients: list[str] = []
  for idx in selected_indices:
    if 1 <= idx <= len(choices_keys):
      clients.append(choices_keys[idx - 1])
    else:
      print(f"Warning: Option '{idx}' is out of range and was skipped.")

  return clients


def main(argv: list[str] | None = None) -> int:
  """CLI entrypoint to configure MCP clients."""
  parser = build_arg_parser()
  args = parser.parse_args(argv)

  project_root = args.project_path if args.project_path else detect_project_root()
  project_root = project_root.resolve()

  print(f"Detected project path: {project_root}")

  # Determine target clients
  target_clients: list[str] = []
  if args.client:
    if "all" in args.client:
      target_clients = list(CLIENT_CHOICES.keys())
    else:
      # De-duplicate
      target_clients = list(dict.fromkeys(args.client))
  else:
    # Run interactive mode
    target_clients = run_interactive_wizard()

  if not target_clients:
    return 0

  # Command parameters for the MCP server
  server_name = "cms-knowledge-base"
  command = "uv"
  mcp_args = ["--directory", str(project_root), "run", "cms-kb-mcp"]

  print(f"\nConfiguring MCP Server: {server_name}")
  print(f"Command: {command}")
  print(f"Arguments: {json.dumps(mcp_args)}\n")

  success_count = 0
  failure_count = 0

  for client in target_clients:
    path = get_default_config_path(client, project_root)
    if not path:
      print(f"Error: Could not resolve configuration path for {client}.")
      failure_count += 1
      continue

    print(f"Target file: {path} ({CLIENT_CHOICES[client]})")

    # Ask for confirmation unless force is set or dry-run is set
    if not args.force and not args.dry_run:
      try:
        confirm = input(f"Configure {CLIENT_CHOICES[client]}? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
          print(f"Skipping {CLIENT_CHOICES[client]}.")
          continue
      except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        return 1

    # Perform update based on format
    if path.suffix == ".json":
      success, msg = update_json_config(
        path, server_name, command, mcp_args, dry_run=args.dry_run
      )
    else:
      success, msg = update_toml_config(
        path, server_name, command, mcp_args, dry_run=args.dry_run
      )

    if success:
      print(msg)
      success_count += 1
    else:
      print(f"ERROR: {msg}", file=sys.stderr)
      failure_count += 1

  print("\nSetup summary:")
  print(f"  Successfully configured: {success_count}")
  print(f"  Failed: {failure_count}")

  return 1 if failure_count > 0 else 0


if __name__ == "__main__":
  sys.exit(main())
