#!/usr/bin/env python3
"""Self-contained validation for agent-harness skills and agent metadata.

Porte de `agent-swarm/codex/scripts/validate_skills.py` — PARAMETRIZADO
(instrução explícita do plano F1): os 3 hardcodes originais viram config,
lida via `engine/_tooling_conf.py`:

  original hardcoded                        -> chave de config (default = valor original)
  ROOT = parents[1] (repo do agent-swarm)    -> _tooling_conf.project_root() (raiz do PROJETO-ALVO,
                                                 não deste pacote — diferente de verify_witness.py)
  SKILL_DIR = ROOT/".agents"/"skills"        -> HARNESS_SKILLS_DIR (default ".agents/skills")
  REQUIRED_SKILLS = ("learnhouse-...", ...)  -> HARNESS_REQUIRED_SKILLS (CSV, default vazio —
                                                 nenhuma skill é obrigatória por padrão; cada
                                                 projeto-alvo declara as suas via copier.yml)
  ".codex"/"agents", ".codex"/"config.toml"  -> HARNESS_CODEX_AGENTS_DIR, HARNESS_CODEX_CONFIG_PATH
  openai.yaml de "learnhouse-delivery-...".  -> HARNESS_COUNCIL_SKILL_NAME (opcional; vazio = pula
                                                 a checagem, fail-open — nem todo projeto tem
                                                 companion OpenAI-interface na skill de council)

Fail-open adicional em relação ao original: se HARNESS_CODEX_AGENTS_DIR /
HARNESS_CODEX_CONFIG_PATH não existirem no projeto-alvo, a validação de
TOML é pulada em vez de falhar — um projeto que só usa Claude (use_codex=
false no copier.yml) não tem `.codex/` para validar.
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
        print("skill-contract: HARNESS_COUNCIL_SKILL_NAME nao configurado — validacao de openai.yaml pulada")
        return
    path = SKILL_DIR / COUNCIL_SKILL_NAME / "agents" / "openai.yaml"
    if not path.exists():
        fail(f"HARNESS_COUNCIL_SKILL_NAME={COUNCIL_SKILL_NAME!r} configurado mas {path} nao existe")
    text = path.read_text(encoding="utf-8")
    for marker in ("interface:", "display_name:", "short_description:", "default_prompt:"):
        if marker not in text:
            fail(f"{path}: missing {marker}")


def validate_toml() -> None:
    if not CODEX_CONFIG_PATH.exists() and not CODEX_AGENTS_DIR.exists():
        print("skill-contract: .codex nao encontrado no projeto-alvo — validacao de TOML pulada (use_codex=false)")
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
