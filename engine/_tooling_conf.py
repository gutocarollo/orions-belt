#!/usr/bin/env python3
"""_tooling_conf — módulo ÚNICO de carregamento da config central do harness.

Por que este módulo existe (o erro que ele corrige): o `guto-wiki`
(docs/planning/research/01-guto-wiki.md §b, "Observações estruturais" item 1)
implementou o MESMO `load_config()`/`config_csv()` (formato `KEY=value`,
comentário `#`, CSV inline) três vezes, byte-a-byte idênticas, em
`docs-wiki-lint.py`, `ref-integrity.py` e `scope-wiki-lint.py` — sem nenhuma
abstração compartilhada entre eles. Este é o DRY que eles próprios não fizeram.
Todo script do `engine/` (hooks, lint, contract) importa `get_config()`/
`get_config_csv()`/`get_config_int()`/`get_config_bool()` daqui em vez de
reimplementar o parser.

Formato do `.harness/harness.conf` (docs/planning/research/03-hardcodes.md §3):

    KEY=value
    # comentário de linha inteira ou trailing (precedido de espaço)
    CSV_KEY=item1,item2,item3          # get_config_csv() faz o split
    DERIVED_KEY=${OUTRA_KEY}-sufixo    # expansão sequencial top-to-bottom,
                                        # mesma semântica de `source` em bash

Zero dependência externa (stdlib puro) — mesma decisão de design do guto-wiki
(docs/planning/research/01-guto-wiki.md §"Observações estruturais" item 2):
`configparser` exigiria seções `[x]` que o formato não usa; `tomllib` é
stdlib só a partir do 3.11. `KEY=value` + `split("#", 1)` é suficiente e roda
em qualquer Python 3.

Consumidores bash (a maioria dos hooks reais do learnhouse são `.sh`, não
`.py` — ver `engine/hooks/subagent-throttle.sh`) não importam este módulo
diretamente; chamam o modo CLI (`python3 _tooling_conf.py get KEY default`).
Isso evita a alternativa óbvia-mas-errada de reimplementar o parser em bash
puro (`source` direto no `.conf` funcionaria para o caso feliz, mas
divergiria silenciosamente do parser Python em 2 pontos: comentário colado
sem espaço antes do `#`, e fallback multi-nome de arquivo) — exatamente o
tipo de duplicação DRY-violável que este módulo existe para evitar.

Fail-open (docs/planning/research/07-autoconfig-patterns.md §Síntese-3):
arquivo ausente, ilegível ou malformado -> os getters devolvem o `default` do
chamador. Nunca levanta exceção, nunca derruba o hook que o invoca.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Nomes candidatos dentro do diretório-raiz encontrado, em ordem de
# precedência (o primeiro que existir vence). Combina duas convenções:
# 1. o par oficial dentro de `.harness/` (convenção deste framework: ver
#    templates/.harness/harness.conf.jinja);
# 2. nomes soltos na raiz do projeto, para compat com quem copiou só o
#    `.conf` sem o diretório, ou migrou de docs-tooling.conf/wiki-tooling.conf
#    (o padrão de fallback de 3 nomes do guto-wiki, adaptado).
_CANDIDATE_RELATIVE_PATHS: tuple[str, ...] = (
    ".harness/harness.conf",
    ".harness/.harness.conf",
    "harness.conf",
    ".harness.conf",
)

# Override de teste/CI: aponta direto para um arquivo .conf, pulando toda a
# resolução de root (usado pelos fixtures em engine/hooks/tests/).
_ENV_CONF_PATH = "HARNESS_CONF_PATH"
# Hints de root, em ordem de precedência quando `start` não é passado
# explicitamente. HARNESS_PROJECT_ROOT é a hint canônica deste framework;
# CLAUDE_PROJECT_DIR é reconhecida porque os hooks Claude Code já a exportam
# (mesmo padrão usado em subagent-throttle.sh original:
# `ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"`).
_ENV_ROOT_HINTS: tuple[str, ...] = ("HARNESS_PROJECT_ROOT", "CLAUDE_PROJECT_DIR")

_VAR_REF_RE = re.compile(r"\$\{(\w+)\}")

_MAX_CLIMB = 64  # teto de segurança — nunca sobe mais que isso


def _find_root_with_candidate(start: Path) -> Path | None:
    """Sobe diretórios a partir de `start` até achar um diretório que
    contenha um dos `_CANDIDATE_RELATIVE_PATHS`, ou até cruzar a raiz de um
    repositório git (não sobe além dela — evita vazar para diretórios de
    usuário fora do projeto), ou até a raiz do filesystem."""
    current = start.resolve()
    for _ in range(_MAX_CLIMB):
        for rel in _CANDIDATE_RELATIVE_PATHS:
            if (current / rel).is_file():
                return current
        if (current / ".git").exists():
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def project_root(start: Path | None = None) -> Path:
    """Resolve a raiz do projeto-alvo para consumidores que precisam de um
    diretório-base além do `.conf` em si (docs_wiki_lint.py, ref_integrity.py,
    validate_skills.py, agent_swarm_ledger.py — engine/lint/ e engine/contract/
    usam esta função em vez de cada um reimplementar
    `git rev-parse --show-toplevel`, o mesmo tipo de duplicação DRY que este
    módulo já corrige para o parser de `.conf`).

    Ordem de precedência: `start` explícito -> HARNESS_PROJECT_ROOT ->
    CLAUDE_PROJECT_DIR -> `git rev-parse --show-toplevel` -> cwd. Fail-open:
    nunca lança exceção; se nada resolver, devolve o cwd."""
    if start is not None:
        return start.resolve()
    for env_name in _ENV_ROOT_HINTS:
        hint = os.environ.get(env_name)
        if hint:
            return Path(hint).resolve()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if out:
                return Path(out).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd().resolve()


def _resolve_conf_path(start: Path | None = None) -> Path | None:
    override = os.environ.get(_ENV_CONF_PATH)
    if override:
        p = Path(override)
        return p if p.is_file() else None

    if start is None:
        root_hint: str | None = None
        for env_name in _ENV_ROOT_HINTS:
            root_hint = os.environ.get(env_name)
            if root_hint:
                break
        start = Path(root_hint) if root_hint else Path.cwd()

    root = _find_root_with_candidate(start)
    if root is None:
        return None
    for rel in _CANDIDATE_RELATIVE_PATHS:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _expand_refs(value: str, values_so_far: dict[str, str]) -> str:
    """Expande `${OUTRA_KEY}` usando as chaves já parseadas até esta linha
    (top-to-bottom) ou variáveis de ambiente — mesma semântica sequencial de
    `source` em bash. Referência não resolvida fica literal (fail-open: não
    levanta erro por chave desconhecida)."""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return values_so_far.get(key, os.environ.get(key, match.group(0)))

    return _VAR_REF_RE.sub(_sub, value)


def load_config(start: Path | None = None) -> dict[str, str]:
    """Localiza e parseia o `.harness/harness.conf` do projeto-alvo (ver
    `_resolve_conf_path`). Fail-open: arquivo ausente ou erro de leitura ->
    dict vazio, nunca exceção."""
    values: dict[str, str] = {}
    path = _resolve_conf_path(start)
    if path is None:
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _expand_refs(value.strip(), values)
        values[key] = value
    return values


_CONF_CACHE: dict[str, str] | None = None


def _conf() -> dict[str, str]:
    global _CONF_CACHE
    if _CONF_CACHE is None:
        _CONF_CACHE = load_config()
    return _CONF_CACHE


def reset_cache_for_tests() -> None:
    """Só para testes: força re-leitura do `.conf` na próxima chamada
    (o processo principal usa cache de processo — hooks são short-lived,
    então isso normalmente não importa fora de testes)."""
    global _CONF_CACHE
    _CONF_CACHE = None


def get_config(key: str, default: str | None = None) -> str | None:
    return _conf().get(key, default)


def get_config_csv(key: str, default: list[str] | None = None) -> list[str]:
    value = _conf().get(key)
    if not value:
        return list(default) if default else []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_config_int(key: str, default: int) -> int:
    """Caps numéricos (docs/planning/research/03-hardcodes.md §2.9) são
    sempre int no schema A. Fail-open: valor ausente ou não-numérico ->
    default."""
    raw = _conf().get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_config_bool(key: str, default: bool) -> bool:
    raw = _conf().get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cli(argv: list[str]) -> int:
    import sys

    if argv and argv[0] == "root":
        print(project_root())
        return 0

    if len(argv) < 2:
        print(
            "usage: _tooling_conf.py {get|getcsv|getint|getbool} KEY [default] | root",
            file=sys.stderr,
        )
        return 1
    cmd, key = argv[0], argv[1]
    default = argv[2] if len(argv) > 2 else None
    if cmd == "get":
        result = get_config(key, default)
        print(result if result is not None else "")
    elif cmd == "getcsv":
        default_list = default.split(",") if default else []
        print(",".join(get_config_csv(key, default_list)))
    elif cmd == "getint":
        print(get_config_int(key, int(default) if default is not None else 0))
    elif cmd == "getbool":
        default_bool = str(default).strip().lower() in {"1", "true", "yes", "on"} if default else False
        print("1" if get_config_bool(key, default_bool) else "0")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_cli(sys.argv[1:]))
