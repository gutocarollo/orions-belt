#!/usr/bin/env python3
"""Run the self-contained agent-harness contract validation suite.

Porte de `agent-swarm/codex/scripts/validate_contract.py` (ver
docs/planning/research/02-agent-swarm.md) para `engine/contract/scripts/`.
Nenhuma mudança de lógica — `ROOT` continua relativo ao próprio script
(`parents[1]` = `engine/contract/`), porque este validador orquestra as
OUTRAS peças do MESMO pacote (schemas/, scripts/, tests/, verification/),
não conteúdo de um projeto-alvo externo. É o mesmo caso de `verify_witness.py`
(ver seu docstring) — self-referential por design, diferente de
`validate_skills.py`/`agent_swarm_ledger.py`, que resolvem a raiz do
projeto-alvo via `_tooling_conf.project_root()`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mini_schema_validate import SchemaValidationError, assert_invalid, assert_valid  # noqa: E402


ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def validate_json_files() -> None:
    for folder in ("schemas", "verification"):
        for path in sorted((ROOT / folder).glob("*.json")):
            json.loads(path.read_text(encoding="utf-8"))
            print(f"json-ok {path.relative_to(ROOT)}", flush=True)


def validate_schema_examples() -> None:
    """M2/H4 (auditoria adversarial): valida INSTÂNCIAS de exemplo contra os
    schemas de verdade (mini_schema_validate.py, stdlib puro -- ver docstring
    do módulo para a decisão de não depender de `jsonschema`). Antes desta
    função, `validate_json_files()` só fazia `json.loads()` nos schemas --
    nunca provava que um `allOf/if/then` REJEITA uma instância que o viola.
    Prova de mutação (rodar manualmente ao mexer num schema): trocar o
    `then` de um schema por uma regra inócua e checar que os fixtures em
    `schemas/examples/invalid/` passam a levantar erro AQUI (antes,
    silenciosamente ficavam verdes)."""
    schemas_dir = ROOT / "schemas"
    examples_dir = schemas_dir / "examples"
    schema_cache: dict[str, dict] = {}

    def load_schema(name: str) -> dict:
        if name not in schema_cache:
            schema_path = schemas_dir / f"{name}.schema.json"
            if not schema_path.exists():
                raise SystemExit(f"fixture referencia schema inexistente: {schema_path}")
            schema_cache[name] = json.loads(schema_path.read_text(encoding="utf-8"))
        return schema_cache[name]

    valid_dir = examples_dir / "valid"
    invalid_dir = examples_dir / "invalid"
    if not valid_dir.exists() or not invalid_dir.exists():
        raise SystemExit(f"schemas/examples/{{valid,invalid}} ausente -- fixtures de M2/H4 removidas?")

    checked = 0
    for path in sorted(valid_dir.glob("*.json")):
        schema_name = path.name.split(".")[0]
        instance = json.loads(path.read_text(encoding="utf-8"))
        assert_valid(instance, load_schema(schema_name), f"valid/{path.name}")
        print(f"schema-example-ok (valid) {path.relative_to(ROOT)}", flush=True)
        checked += 1

    for path in sorted(invalid_dir.glob("*.json")):
        schema_name = path.name.split(".")[0]
        instance = json.loads(path.read_text(encoding="utf-8"))
        assert_invalid(instance, load_schema(schema_name), f"invalid/{path.name}")
        print(f"schema-example-ok (invalid, corretamente rejeitada) {path.relative_to(ROOT)}", flush=True)
        checked += 1

    if checked == 0:
        raise SystemExit("nenhum fixture em schemas/examples/ -- validate_schema_examples() é no-op, isso é um gap")
    print(f"schema-examples-validated {checked}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-git-check", action="store_true")
    args = parser.parse_args()

    validate_json_files()
    try:
        validate_schema_examples()
    except SchemaValidationError as exc:
        for error in exc.errors:
            print(f"schema-example-FAIL: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    run([sys.executable, "scripts/validate_skills.py"])
    run([sys.executable, "scripts/verify_witness.py"])
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    if not args.skip_git_check:
        run(["git", "diff", "--check"])
    print("contract-validation-ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
