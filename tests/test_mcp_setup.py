from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from cms_kb.mcp_setup import (
  detect_project_root,
  get_default_config_path,
  main,
  update_json_config,
  update_toml_config,
  update_toml_string,
)


def test_detect_project_root() -> None:
  root = detect_project_root()
  assert root.is_dir()
  assert (root / "pyproject.toml").is_file() or root.name == "resdac-knowledge-base"


def test_get_default_config_path(tmp_path: Path) -> None:
  # Test with mock platforms passing tmp_path as home to avoid real home access
  with mock.patch("sys.platform", "linux"):
    p = get_default_config_path("claude-desktop", tmp_path, home=tmp_path)
    assert p is not None
    assert p.parts[-3:] == (".config", "Claude", "claude_desktop_config.json")
    assert str(p).startswith(str(tmp_path))

  with mock.patch("sys.platform", "darwin"):
    p = get_default_config_path("claude-desktop", tmp_path, home=tmp_path)
    assert p is not None
    assert p.parts[-4:] == (
      "Library",
      "Application Support",
      "Claude",
      "claude_desktop_config.json",
    )
    assert str(p).startswith(str(tmp_path))

  with mock.patch("sys.platform", "win32"):
    with mock.patch.dict("os.environ", {"APPDATA": "/AppData"}):
      p = get_default_config_path("claude-desktop", tmp_path, home=tmp_path)
      assert p is not None
      assert Path("/AppData/Claude/claude_desktop_config.json") == p

  p_claude_project = get_default_config_path("claude-code-project", tmp_path, home=tmp_path)
  assert p_claude_project == tmp_path / ".mcp.json"

  p_claude_user = get_default_config_path("claude-code-user", tmp_path, home=tmp_path)
  assert p_claude_user is not None
  assert p_claude_user == tmp_path / ".claude.json"

  p_antigravity = get_default_config_path("antigravity", tmp_path, home=tmp_path)
  assert p_antigravity is not None
  assert p_antigravity == tmp_path / ".gemini" / "antigravity-cli" / "mcp_config.json"

  p_codex_project = get_default_config_path("codex-project", tmp_path, home=tmp_path)
  assert p_codex_project == tmp_path / ".codex" / "config.toml"


def test_update_json_config_creation(tmp_path: Path) -> None:
  config_path = tmp_path / "test_config.json"
  success, msg = update_json_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success is True
  assert "Successfully configured" in msg

  # Verify file content
  with open(config_path, "r", encoding="utf-8") as f:
    data = json.load(f)
  assert "mcpServers" in data
  assert data["mcpServers"]["cms-kb"] == {
    "command": "uv",
    "args": ["run", "mcp"],
  }


def test_update_json_config_merge(tmp_path: Path) -> None:
  config_path = tmp_path / "test_config.json"
  initial_data = {
    "other_key": "other_value",
    "mcpServers": {
      "other-server": {
        "command": "node",
        "args": [],
      }
    }
  }
  config_path.parent.mkdir(parents=True, exist_ok=True)
  with open(config_path, "w", encoding="utf-8") as f:
    json.dump(initial_data, f)

  success, msg = update_json_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success is True

  with open(config_path, "r", encoding="utf-8") as f:
    data = json.load(f)
  assert data["other_key"] == "other_value"
  assert "other-server" in data["mcpServers"]
  assert data["mcpServers"]["cms-kb"] == {
    "command": "uv",
    "args": ["run", "mcp"],
  }


def test_update_json_config_invalid_json(tmp_path: Path) -> None:
  config_path = tmp_path / "test_config.json"
  config_path.parent.mkdir(parents=True, exist_ok=True)
  with open(config_path, "w", encoding="utf-8") as f:
    f.write("invalid json contents")

  success, msg = update_json_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success is False
  assert "invalid JSON" in msg


def test_update_json_config_already_configured(tmp_path: Path) -> None:
  config_path = tmp_path / "test_config.json"
  success, msg1 = update_json_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success is True

  success2, msg2 = update_json_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success2 is True
  assert "Already configured and up-to-date" in msg2


def test_update_toml_string() -> None:
  # Append to empty
  res1 = update_toml_string("", "cms-kb", "uv", ["run", "mcp"])
  expected1 = (
    "[mcp_servers.cms-kb]\n"
    'type = "stdio"\n'
    'command = "uv"\n'
    'args = ["run", "mcp"]\n'
  )
  assert res1.strip() == expected1.strip()

  # Append to existing
  existing = (
    "[features]\n"
    "use_mcp = true\n"
  )
  res2 = update_toml_string(existing, "cms-kb", "uv", ["run", "mcp"])
  assert "use_mcp = true" in res2
  assert "[mcp_servers.cms-kb]" in res2

  # Replace existing and preserve surrounding sections
  existing_with_mcp = (
    "[mcp_servers.cms-kb]\n"
    'type = "stdio"\n'
    'command = "old-command"\n'
    'args = ["old-args"]\n'
    "\n"
    "[other_section]\n"
    "key = 123"
  )
  res3 = update_toml_string(existing_with_mcp, "cms-kb", "uv", ["run", "mcp"])
  assert "old-command" not in res3
  assert 'command = "uv"' in res3
  assert "[other_section]" in res3
  assert "key = 123" in res3


def test_update_toml_string_quoted_and_preserved_comments() -> None:
  # Verify quoted header support and preservation of inner comments
  existing_with_mcp_quoted = (
    '[mcp_servers."cms-kb"]\n'
    'type = "stdio"\n'
    "# A comment we must preserve\n"
    'command = "old-command"\n'
    'args = ["old-args"]\n'
    "custom_setting = true\n"
    "command_timeout = 30\n"
    'type_custom = "foo"\n'
    "\n"
    "[other_section]"
  )
  res = update_toml_string(existing_with_mcp_quoted, "cms-kb", "uv", ["run", "mcp"])
  assert 'command = "uv"' in res
  # Check comment is still present in output
  assert "# A comment we must preserve" in res
  # Check custom settings are still present in output
  assert "custom_setting = true" in res
  assert "command_timeout = 30" in res
  assert 'type_custom = "foo"' in res


def test_update_toml_config(tmp_path: Path) -> None:
  config_path = tmp_path / "config.toml"
  success, msg = update_toml_config(
    config_path, "cms-kb", "uv", ["run", "mcp"]
  )
  assert success is True
  assert "Successfully configured" in msg

  with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()
  assert "[mcp_servers.cms-kb]" in content
  assert 'command = "uv"' in content

  # Test dry run
  success_dry, msg_dry = update_toml_config(
    config_path, "cms-kb", "uv", ["run", "mcp", "new-flag"], dry_run=True
  )
  assert success_dry is True
  assert "[DRY-RUN]" in msg_dry

  # Check that file did not change
  with open(config_path, "r", encoding="utf-8") as f:
    content_after = f.read()
  assert "new-flag" not in content_after


def test_main_cli_dry_run(tmp_path: Path) -> None:
  # Run main CLI with dry-run and project-path overrides
  exit_code = main([
    "--client", "claude-code-project",
    "--client", "codex-project",
    "--project-path", str(tmp_path),
    "--dry-run",
    "--force",
  ])
  assert exit_code == 0


def test_main_cli_non_tty_error() -> None:
  # With stdin mocked to non-TTY, calling setup with no client should error out
  with mock.patch("sys.stdin.isatty", return_value=False):
    exit_code = main([])
    assert exit_code == 1
