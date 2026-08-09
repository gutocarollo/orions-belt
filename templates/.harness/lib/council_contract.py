#!/usr/bin/env python3
"""Semantic contract validator for the installed Delivery Council."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sync_council import council_paths


SCHEMA_NAMES = (
    "phase-plan-result.schema.json",
    "item-plan-result.schema.json",
    "execution-item-result.schema.json",
    "quality-review-result.schema.json",
    "simplification-result.schema.json",
    "adversarial-review-result.schema.json",
    "delivery-result.schema.json",
    "slice-event.schema.json",
    "validation-event.schema.json",
    "local-commit-event.schema.json",
    "delivery-manifest.schema.json",
    "objective-impact.schema.json",
    "execution-graph.schema.json",
    "code-necessity-report.schema.json",
)
MARKER_GROUPS = (
    ("MUTATION_MODE=READ_ONLY | WORKSPACE_WRITE",),
    ("planning-and-task-breakdown",),
    ("incremental-implementation",),
    ("Cada slice validado DEVE produzir imediatamente um commit LOCAL atomico", "Every validated slice MUST immediately produce an atomic LOCAL commit"),
    ("Push para qualquer remoto e merge para `main` no remoto exigem autorizacao explicita", "Push to any remote and merge to remote `main` require explicit authorization"),
    ("Critical`, `Required`, `Optional`, `Nit`, `FYI", "canonical taxonomy is `Critical`"),
    ("zero `Critical` e zero `Required`", "zero `Critical` and zero `Required`"),
    ("Maquina de estados obrigatoria", "Mandatory state machine"),
    ("QUALITY-FIX-REQUEST",),
    ("FIX-CONSUMED",),
    ("Limite: maximo de 2 rodadas", "Limit: maximum 2 rounds"),
    ("Limite: maximo de 3 rodadas", "Limit: maximum 3 rounds"),
    ("subagent isolado `code-reviewer`", "isolated `code-reviewer` subagent"),
)


class ContractError(ValueError):
    pass


def validate_contract(root: Path) -> dict[str, Any]:
    source, target = council_paths(root)
    surfaces = [path for path in (source, target) if path.is_file()]
    if not surfaces:
        raise ContractError("at least one Council skill surface is required")
    source_bytes = surfaces[0].read_bytes()
    if len(surfaces) == 2 and source_bytes != surfaces[1].read_bytes():
        raise ContractError("Council skill surfaces drifted")
    text = source_bytes.decode("utf-8")
    project = surfaces[0].parent.name.removesuffix("-delivery-council")
    marker_groups = MARKER_GROUPS + ((f"subagent `{project}-adversarial-reviewer`", f"`{project}-adversarial-reviewer` subagent"),)
    missing = [" | ".join(group) for group in marker_groups if not any(marker in text for marker in group)]
    if missing:
        raise ContractError("missing Council semantic markers: " + ", ".join(missing))
    schema_dir = root / ".harness" / "schemas"
    for name in SCHEMA_NAMES:
        path = schema_dir / name
        if not path.is_file():
            raise ContractError(f"missing schema: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "object" or data.get("additionalProperties") is not False or not data.get("required"):
            raise ContractError(f"invalid strict schema: {path}")
    return {"status": "PASS", "schemas": len(SCHEMA_NAMES), "markers": len(marker_groups)}
