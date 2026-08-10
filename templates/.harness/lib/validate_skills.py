#!/usr/bin/env python3
"""Validate installed skills, runtime-native agents and Council contracts."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from _tooling_conf import get_config, get_config_csv, project_root
from council_contract import ContractError, validate_contract

ROOT = project_root()
SKILL_DIR = ROOT / get_config("HARNESS_SKILLS_DIR", ".agents/skills")
REQUIRED_SKILLS = tuple(get_config_csv("HARNESS_REQUIRED_SKILLS", []))
CODEX_AGENTS_DIR = ROOT / get_config("HARNESS_CODEX_AGENTS_DIR", ".codex/agents")
CODEX_CONFIG_PATH = ROOT / get_config("HARNESS_CODEX_CONFIG_PATH", ".codex/config.toml")
COUNCIL_SKILL_NAME = get_config("HARNESS_COUNCIL_SKILL_NAME", "") or ""
CONTEXT_ENABLED = (ROOT / ".harness/context-delivery.enabled").is_file()


def fail(message: str) -> None:
    raise SystemExit(message)


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read metadata {path}: {exc}")
    if not text.startswith("---\n"):
        fail(f"{path}: missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail(f"{path}: unterminated YAML frontmatter")
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "-")):
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
        return
    path = SKILL_DIR / COUNCIL_SKILL_NAME / "agents/openai.yaml"
    if not path.is_file():
        fail(f"configured council metadata does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    for marker in ("interface:", "display_name:", "short_description:", "default_prompt:"):
        if marker not in text:
            fail(f"{path}: missing {marker}")


def _codex_config() -> dict:
    if not CODEX_CONFIG_PATH.is_file():
        return {}
    data = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
    agents = data.get("agents", {})
    if "max_depth" in agents:
        fail(f"{CODEX_CONFIG_PATH}: max_depth is not emitted by the current contract")
    if "max_threads" in agents:
        fail(f"{CODEX_CONFIG_PATH}: use canonical agents.max_concurrent_threads_per_session, not legacy max_threads")
    if "max_concurrent_threads_per_session" not in agents:
        fail(f"{CODEX_CONFIG_PATH}: missing agents.max_concurrent_threads_per_session")
    return data


def validate_toml() -> dict:
    config = _codex_config()
    if CODEX_AGENTS_DIR.is_dir():
        for path in sorted(CODEX_AGENTS_DIR.glob("*.toml")):
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for field in ("name", "description", "sandbox_mode", "developer_instructions"):
                if field not in data:
                    fail(f"{path}: missing {field}")
            if path.stem.endswith(("-context-scout", "-context-shard")) and not data.get("model"):
                fail(f"{path}: context agent must pin model")
    return config


def _expected_models() -> dict[str, dict[str, str]]:
    return {
        "Claude": {
            "scout": get_config("HARNESS_CLAUDE_CONTEXT_SCOUT_MODEL", "sonnet"),
            "shard": get_config("HARNESS_CLAUDE_CONTEXT_SHARD_MODEL", "haiku"),
        },
        "Codex": {
            "scout": get_config("HARNESS_CODEX_CONTEXT_SCOUT_MODEL", "gpt-5.6-terra"),
            "shard": get_config("HARNESS_CODEX_CONTEXT_SHARD_MODEL", "gpt-5.6-luna"),
        },
    }


def validate_context_delivery(codex_config: dict) -> None:
    if not CONTEXT_ENABLED:
        return
    required_files = (
        ".harness/lib/context_predicates.py",
        ".harness/lib/context_provider_probe.py",
        ".harness/lib/context_routing.py",
        ".harness/lib/context_receipt_fields.py",
        ".harness/lib/context_evidence.py",
        ".harness/lib/context_delivery.py",
        ".harness/lib/codex_context_receipts.py",
        ".harness/lib/secure_runtime_io.py",
        ".harness/schemas/context-plan-result.schema.json",
        ".harness/schemas/context-delivery-result.schema.json",
        ".harness/hooks/context-tool-ledger.py",
        ".harness/hooks/subagent-lifecycle-ledger.py",
    )
    for name in required_files:
        if not (ROOT / name).is_file():
            fail(f"missing Context Delivery file: {name}")

    expected = _expected_models()
    for runtime, folder, suffix in (
        ("Claude", ROOT / ".claude/agents", ".md"),
        ("Codex", ROOT / ".codex/agents", ".toml"),
    ):
        if not folder.is_dir():
            continue
        for role, model in expected[runtime].items():
            matches = list(folder.glob(f"*-context-{role}{suffix}"))
            if len(matches) != 1:
                fail(f"{runtime}: expected exactly one context-{role} agent, got {len(matches)}")
            path = matches[0]
            actual = parse_frontmatter(path).get("model") if suffix == ".md" else tomllib.loads(path.read_text(encoding="utf-8")).get("model")
            if actual != model:
                fail(f"{path}: model={actual!r}, expected configured {model!r}")

    for skill_root in (ROOT / ".claude/skills", ROOT / ".agents/skills"):
        if skill_root.is_dir() and not (skill_root / "context-delivery/SKILL.md").is_file():
            fail(f"runtime skill surface lacks context-delivery: {skill_root}")

    context_provider = get_config("HARNESS_CONTEXT_PROVIDER", "none")
    if context_provider == "codegraph":
        manifest = ROOT / ".harness/context-providers/code-graph.json"
        if not manifest.is_file():
            fail("CodeGraph provider configured but capability manifest is missing")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("manifest_schema_version") != 2:
            fail(f"{manifest}: manifest_schema_version must be 2")
        if (ROOT / ".codex").is_dir() and "codegraph" not in codex_config.get("mcp_servers", {}):
            fail("Codex Context Delivery with CodeGraph requires [mcp_servers.codegraph]")
        if (ROOT / ".claude").is_dir():
            mcp_path = ROOT / ".mcp.json"
            if not mcp_path.is_file():
                fail("Claude Context Delivery with CodeGraph requires project-scoped .mcp.json")
            mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            server = mcp.get("mcpServers", {}).get("codegraph", {})
            if server.get("command") != "codegraph" or server.get("args") != ["serve", "--mcp"]:
                fail(f"{mcp_path}: invalid CodeGraph stdio server configuration")

    lsp_provider = get_config("HARNESS_LSP_PROVIDER", "none")
    if lsp_provider == "serena":
        manifest = ROOT / ".harness/context-providers/serena.json"
        if not manifest.is_file() or not (ROOT / ".harness/hooks/serena-health-gate.py").is_file():
            fail("Serena configured without its manifest and health gate")


def main() -> int:
    codex_present = CODEX_CONFIG_PATH.exists() or CODEX_AGENTS_DIR.exists()
    if codex_present and not REQUIRED_SKILLS:
        fail("HARNESS_REQUIRED_SKILLS must declare the installed contract skills")
    if codex_present and not COUNCIL_SKILL_NAME:
        fail("HARNESS_COUNCIL_SKILL_NAME is required when Codex configuration is present")
    if COUNCIL_SKILL_NAME and COUNCIL_SKILL_NAME not in REQUIRED_SKILLS:
        fail("HARNESS_COUNCIL_SKILL_NAME must also be listed in HARNESS_REQUIRED_SKILLS")
    for skill in REQUIRED_SKILLS:
        validate_skill(skill)
    validate_openai_yaml()
    codex_config = validate_toml()
    validate_context_delivery(codex_config)
    if COUNCIL_SKILL_NAME:
        try:
            validate_contract(ROOT)
        except ContractError as exc:
            fail(str(exc))
    print("skill-contract-ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except tomllib.TOMLDecodeError as exc:
        sys.stderr.write(f"TOML parse error: {exc}\n")
        raise SystemExit(1)
