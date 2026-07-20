#!/usr/bin/env python3
"""Self-contained validation for agent-harness skills and agent metadata.

Port of `agent-swarm/codex/scripts/validate_skills.py` — PARAMETERIZED
(explicit instruction of plan F1): the 3 original hardcodes became config,
read via `engine/_tooling_conf.py`:

  original hardcoded                         -> config key (default = original value)
  ROOT = parents[1] (agent-swarm repo)        -> _tooling_conf.project_root() (TARGET PROJECT root,
                                                  not this package — unlike verify_witness.py)
  SKILL_DIR = ROOT/".agents"/"skills"         -> HARNESS_SKILLS_DIR (default ".agents/skills")
  REQUIRED_SKILLS = ("learnhouse-...", ...)   -> HARNESS_REQUIRED_SKILLS (CSV, empty default —
                                                  no skill is required by default; each
                                                  target project declares its own via copier.yml)
  ".codex"/"agents", ".codex"/"config.toml"   -> HARNESS_CODEX_AGENTS_DIR, HARNESS_CODEX_CONFIG_PATH
  openai.yaml of "learnhouse-delivery-...".   -> HARNESS_COUNCIL_SKILL_NAME (optional; empty = skips
                                                  the check, fail-open — not every project has a
                                                  companion OpenAI-interface in the council skill)

Additional fail-open relative to the original: if HARNESS_CODEX_AGENTS_DIR /
HARNESS_CODEX_CONFIG_PATH do not exist in the target project, the TOML
validation is skipped instead of failing — a project that only uses Claude
(use_codex=false in copier.yml) has no `.codex/` to validate.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # engine/
from _tooling_conf import get_config, get_config_csv, project_root  # noqa: E402


ROOT = project_root()
SKILL_DIR = ROOT / get_config("HARNESS_SKILLS_DIR", ".agents/skills")
REQUIRED_SKILLS = tuple(get_config_csv("HARNESS_REQUIRED_SKILLS", []))
CODEX_AGENTS_DIR = ROOT / get_config("HARNESS_CODEX_AGENTS_DIR", ".codex/agents")
CODEX_CONFIG_PATH = ROOT / get_config("HARNESS_CODEX_CONFIG_PATH", ".codex/config.toml")
COUNCIL_SKILL_NAME = get_config("HARNESS_COUNCIL_SKILL_NAME", "") or ""


def fail(message: str) -> None:
    raise SystemExit(message)


def parse_frontmatter(path: pathlib.Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(f"{path}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail(f"{path}: unterminated YAML frontmatter")
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def validate_skill(name: str) -> None:
    folder = SKILL_DIR / name
    if not folder.is_dir():
        fail(f"missing skill folder: {folder}")
    metadata = parse_frontmatter(folder / "SKILL.md")
    if metadata.get("name") != name:
        fail(f"{folder}/SKILL.md: name must be {name}")
    if not metadata.get("description"):
        fail(f"{folder}/SKILL.md: description is required")


def validate_openai_yaml() -> None:
    if not COUNCIL_SKILL_NAME:
        print("skill-contract: HARNESS_COUNCIL_SKILL_NAME not configured — openai.yaml validation skipped")
        return
    path = SKILL_DIR / COUNCIL_SKILL_NAME / "agents" / "openai.yaml"
    if not path.exists():
        fail(f"HARNESS_COUNCIL_SKILL_NAME={COUNCIL_SKILL_NAME!r} configured but {path} does not exist")
    text = path.read_text(encoding="utf-8")
    for marker in ("interface:", "display_name:", "short_description:", "default_prompt:"):
        if marker not in text:
            fail(f"{path}: missing {marker}")


def validate_toml() -> None:
    if not CODEX_CONFIG_PATH.exists() and not CODEX_AGENTS_DIR.exists():
        print("skill-contract: .codex not found in target project — TOML validation skipped (use_codex=false)")
        return
    if CODEX_CONFIG_PATH.exists():
        tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
    if CODEX_AGENTS_DIR.exists():
        for path in sorted(CODEX_AGENTS_DIR.glob("*.toml")):
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for field in ("name", "description", "sandbox_mode", "developer_instructions"):
                if field not in data:
                    fail(f"{path}: missing {field}")


def main() -> int:
    for skill in REQUIRED_SKILLS:
        validate_skill(skill)
    validate_openai_yaml()
    validate_toml()
    print("skill-contract-ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except tomllib.TOMLDecodeError as exc:
        sys.stderr.write(f"TOML parse error: {exc}\n")
        raise SystemExit(1)
