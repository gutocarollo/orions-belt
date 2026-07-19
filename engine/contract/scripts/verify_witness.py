#!/usr/bin/env python3
"""Verify load-bearing agent-harness contract markers.

Porte de `agent-swarm/codex/scripts/verify_witness.py` — a lógica central
(`verify()`) não mudou. `ROOT = Path(__file__).resolve().parents[1]` (=
`engine/contract/`) continua o default self-referential, usado pelo
`--witness` default (`verification/witness-fixes.json`, protege o PRÓPRIO
`engine/contract/`) — ao contrário de `validate_skills.py`/
`agent_swarm_ledger.py`, que resolvem a raiz do PROJETO-ALVO via
`_tooling_conf.project_root()`.

Adição (F1.5): flag `--root <path>` — pequena generalização para verificar
witness de conteúdo FORA de `engine/contract/`, sem quebrar o default
self-referential (quem não passa `--root` continua exatamente como antes).
Uso real: `templates/verification/council-witness.json` protege o
merge do council em `templates/`, resolvido com `--root
templates`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_WITNESS = ROOT / "verification" / "witness-fixes.json"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_witness(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "agent-swarm-witness/v1":
        raise SystemExit(f"{path.relative_to(ROOT)}: unsupported schema")
    fixes = data.get("fixes")
    if not isinstance(fixes, list) or not fixes:
        raise SystemExit(f"{path.relative_to(ROOT)}: fixes must be a non-empty list")
    return data


def verify(path: pathlib.Path, root: pathlib.Path = ROOT) -> tuple[list[dict[str, Any]], list[str]]:
    data = load_witness(path)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for fix in data["fixes"]:
        fix_id = str(fix.get("id", ""))
        rel_file = str(fix.get("file", ""))
        marker = str(fix.get("marker", ""))
        if not fix_id or fix_id in seen_ids:
            errors.append(f"invalid or duplicate id: {fix_id!r}")
            continue
        seen_ids.add(fix_id)
        if len(marker) < 10:
            errors.append(f"{fix_id}: marker is too short")
            continue
        target = root / rel_file
        if not target.exists():
            errors.append(f"{fix_id}: missing file {rel_file}")
            continue
        text = target.read_text(encoding="utf-8")
        present = marker in text
        if not present:
            errors.append(f"{fix_id}: marker missing from {rel_file}")
        results.append(
            {
                "id": fix_id,
                "file": rel_file,
                "markerVerified": present,
                "fileSha256": sha256(text),
            }
        )
    return results, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--witness", type=pathlib.Path, default=DEFAULT_WITNESS)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=ROOT,
        help=(
            "Diretório-base contra o qual os `file:` do witness resolvem "
            "(default: engine/contract/, self-referential — protege o "
            "próprio pacote). Override usado por conteúdo fora do pacote, "
            "ex.: templates/verification/council-witness.json "
            "protegendo o merge do council em templates/."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results, errors = verify(args.witness, args.root)
    output = {"total": len(results), "verified": sum(1 for item in results if item["markerVerified"]), "errors": errors, "results": results}
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"witness: {output['verified']}/{output['total']} verified")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
