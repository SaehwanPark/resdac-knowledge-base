#!/usr/bin/env python3
"""Validate the CMS KB harness structure and naming conventions."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = [
  ROOT / ".agents/skills/cms-kb-orchestrator/SKILL.md",
  ROOT / ".agents/skills/cms-kb-archive/SKILL.md",
  ROOT / ".agents/skills/cms-kb-extraction/SKILL.md",
  ROOT / ".agents/skills/cms-kb-qa/SKILL.md",
]
TEAM_SPEC = ROOT / "docs/harness/cms-kb/team-spec.md"
REQUIRED_SECTIONS = [
  "when to use",
  "required inputs",
  "workflow",
  "expected outputs",
  "validation notes",
  "stop conditions",
]


def parse_frontmatter(text: str) -> dict[str, str]:
  lines = text.splitlines()
  if not lines or lines[0].strip() != "---":
    raise ValueError("missing YAML frontmatter start")

  end = None
  for index, line in enumerate(lines[1:], start=1):
    if line.strip() == "---":
      end = index
      break
  if end is None:
    raise ValueError("missing YAML frontmatter end")

  data: dict[str, str] = {}
  for raw_line in lines[1:end]:
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if ":" not in line:
      raise ValueError(f"invalid frontmatter line: {raw_line!r}")
    key, value = line.split(":", 1)
    data[key.strip()] = value.strip().strip('"')
  return data


def has_heading(text: str, heading: str) -> bool:
  pattern = re.compile(
    rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE
  )
  return bool(pattern.search(text))


def check_skill(path: Path) -> list[str]:
  problems: list[str] = []
  text = path.read_text(encoding="utf-8")

  try:
    frontmatter = parse_frontmatter(text)
  except ValueError as exc:
    return [f"{path}: {exc}"]

  if not frontmatter.get("name"):
    problems.append(f"{path}: frontmatter missing name")
  if not frontmatter.get("description"):
    problems.append(f"{path}: frontmatter missing description")

  for section in REQUIRED_SECTIONS:
    if not has_heading(text, section):
      problems.append(f"{path}: missing section '## {section}'")

  return problems


def check_team_spec(path: Path) -> list[str]:
  problems: list[str] = []
  text = path.read_text(encoding="utf-8")

  required_terms = [
    "cms-kb-orchestrator",
    "cms-kb-archive",
    "cms-kb-extraction",
    "cms-kb-qa",
    "_workspace/01_request.md",
    "_workspace/02_source_inventory.md",
    "_workspace/03_archive_manifest.md",
    "_workspace/04_extraction_pack.md",
    "_workspace/05_qa_review.md",
  ]

  for term in required_terms:
    if term not in text:
      problems.append(f"{path}: missing required term {term!r}")

  return problems


def main() -> int:
  problems: list[str] = []

  for skill in SKILLS:
    if not skill.exists():
      problems.append(f"missing skill file: {skill}")
      continue
    problems.extend(check_skill(skill))

  if not TEAM_SPEC.exists():
    problems.append(f"missing team spec: {TEAM_SPEC}")
  else:
    problems.extend(check_team_spec(TEAM_SPEC))

  if problems:
    for problem in problems:
      print(problem)
    return 1

  print("harness validation passed")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
