#!/usr/bin/env python3
"""Render curated JSONL to deterministic Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


FIELDS = [
    ("user_requests", "Pedidos Do Usuario"),
    ("assistant_conclusions", "Conclusoes Da IA"),
    ("files_analyzed", "Arquivos E Artefatos Analisados"),
    ("commands_or_tools", "Comandos E Ferramentas"),
    ("decisions", "Decisoes"),
    ("risks_or_open_questions", "Riscos E Abertos"),
    ("gotchas", "Gotchas Operacionais"),
]

DIGEST_FIELDS = [
    ("decisions", "Decisoes"),
    ("risks_or_open_questions", "Riscos E Abertos"),
]


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise SystemExit(f"{path}:{line_no}: record is not an object")
            records.append(obj)
    return records


def first_range_start(record: dict[str, Any]) -> int:
    ranges = record.get("source_ranges")
    if isinstance(ranges, list) and ranges:
        first = ranges[0]
        if isinstance(first, dict) and isinstance(first.get("start"), int):
            return int(first["start"])
    return 10**12


def render_list(items: Any) -> list[str]:
    if not isinstance(items, list) or not items:
        return ["- Nao registrado."]
    rendered = []
    for item in items:
        if isinstance(item, str):
            rendered.append(f"- {item}")
        else:
            rendered.append(f"- `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`")
    return rendered


def render_ranges(record: dict[str, Any]) -> str:
    ranges = record.get("source_ranges")
    if not isinstance(ranges, list) or not ranges:
        return "sem range"
    parts = []
    for item in ranges:
        if isinstance(item, dict):
            parts.append(f"{item.get('start', '?')}-{item.get('end', '?')}")
    return ", ".join(parts) if parts else "sem range"


def render_evidence(record: dict[str, Any]) -> list[str]:
    evidence = record.get("evidence_quotes")
    if not isinstance(evidence, list) or not evidence:
        return ["- Nao registrado."]
    lines = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).replace("\n", " ").strip()
        note = str(item.get("note", "")).strip()
        source_range = item.get("source_range", {})
        if isinstance(source_range, dict):
            range_label = f"{source_range.get('start', '?')}-{source_range.get('end', '?')}"
        else:
            range_label = "?"
        suffix = f" - {note}" if note else ""
        lines.append(f"- Linhas {range_label}: \"{quote}\"{suffix}")
    return lines or ["- Nao registrado."]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path, help="Curated JSONL file")
    parser.add_argument("--source", type=Path, help="Source transcript")
    parser.add_argument("--out", type=Path, required=True, help="Markdown output path")
    parser.add_argument("--title", default="Curadoria De Contexto Longo", help="Markdown title")
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Render the compact rehydration digest (resumo+decisoes+riscos+gotchas) instead of the full document",
    )
    args = parser.parse_args()

    jsonl_path = args.jsonl.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    records = sorted(load_records(jsonl_path), key=first_range_start)

    lines: list[str] = [f"# {args.title}", ""]
    lines.append("## Metadados")
    lines.append("")
    lines.append(f"- Curated JSONL: `{jsonl_path}`")
    if args.source:
        source_path = args.source.expanduser().resolve()
        lines.append(f"- Fonte: `{source_path}`")
        if source_path.is_file():
            lines.append(f"- SHA-256 fonte: `{sha256_path(source_path)}`")
    lines.append(f"- Registros: {len(records)}")
    lines.append("")

    if args.digest:
        gotchas: list[str] = []
        for record in records:
            for item in record.get("gotchas", []) or []:
                if isinstance(item, str):
                    gotchas.append(f"- [{record.get('id', '?')}] {item}")
        if gotchas:
            lines.append("## Gotchas (leia antes de agir)")
            lines.append("")
            lines.extend(gotchas)
            lines.append("")
        for record in records:
            rec_id = record.get("id", "?")
            title = record.get("title") or "Sem titulo"
            lines.append(f"## {rec_id}: {title} (linhas {render_ranges(record)})")
            lines.append("")
            lines.append(str(record.get("summary") or "Nao registrado."))
            lines.append("")
            for field, heading in DIGEST_FIELDS:
                items = record.get(field)
                if isinstance(items, list) and items:
                    lines.append(f"### {heading}")
                    lines.append("")
                    lines.extend(render_list(items))
                    lines.append("")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(json.dumps({"out": str(out_path), "record_count": len(records), "mode": "digest"}, ensure_ascii=False, sort_keys=True))
        return 0

    lines.append("## Indice")
    lines.append("")
    for record in records:
        rec_id = record.get("id", "?")
        title = record.get("title") or record.get("summary", "")[:80] or "Sem titulo"
        lines.append(f"- {rec_id}: {title} (linhas {render_ranges(record)})")
    lines.append("")

    for record in records:
        rec_id = record.get("id", "?")
        title = record.get("title") or "Sem titulo"
        lines.append(f"## {rec_id}: {title}")
        lines.append("")
        lines.append(f"- Tipo: `{record.get('kind', '?')}`")
        lines.append(f"- Linhas fonte: {render_ranges(record)}")
        confidence = record.get("confidence")
        if confidence:
            lines.append(f"- Confianca: `{confidence}`")
        tags = record.get("canonical_tags")
        if isinstance(tags, list) and tags:
            lines.append(f"- Tags: {', '.join(str(tag) for tag in tags)}")
        lines.append("")
        lines.append("### Resumo")
        lines.append("")
        lines.append(str(record.get("summary") or "Nao registrado."))
        lines.append("")
        for field, heading in FIELDS:
            lines.append(f"### {heading}")
            lines.append("")
            lines.extend(render_list(record.get(field)))
            lines.append("")
        lines.append("### Evidencias")
        lines.append("")
        lines.extend(render_evidence(record))
        notes = record.get("curator_notes")
        if notes:
            lines.append("")
            lines.append("### Notas Da Curadoria")
            lines.append("")
            lines.append(str(notes))
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out_path), "record_count": len(records)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
