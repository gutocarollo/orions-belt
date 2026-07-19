#!/usr/bin/env python3
"""Validate curated JSONL against a source transcript."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "id": str,
    "kind": str,
    "title": str,
    "source_file": str,
    "source_sha256": str,
    "source_ranges": list,
    "summary": str,
    "user_requests": list,
    "assistant_conclusions": list,
    "files_analyzed": list,
    "commands_or_tools": list,
    "decisions": list,
    "risks_or_open_questions": list,
    "evidence_quotes": list,
}

ALLOWED_KINDS = {"episode", "chunk_curation", "global_summary", "decision_log", "open_items"}

OPTIONAL_LIST_FIELDS = ("gotchas", "dropped_values")


def load_values_ledger(manifest_path: Path) -> list[dict[str, Any]]:
    """Flatten the per-chunk values_ledger from chunks_manifest.json."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger: list[dict[str, Any]] = []
    for chunk in manifest.get("chunks", []):
        for item in chunk.get("values_ledger", []):
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                ledger.append(item)
    return ledger


def check_values_coverage(
    records: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    strict: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Anti-genericization gate: every ledger value inside a record's source
    ranges must appear verbatim in the record or be listed in dropped_values."""
    for record in records:
        rec_id = str(record.get("id", "?"))
        ranges = [
            (item.get("start"), item.get("end"))
            for item in record.get("source_ranges", [])
            if isinstance(item, dict)
        ]
        dropped = {str(v) for v in record.get("dropped_values", []) if isinstance(v, str)}
        blob = json.dumps(record, ensure_ascii=False)
        for entry in ledger:
            line = entry.get("line")
            if not isinstance(line, int) or not any(
                isinstance(s, int) and isinstance(e, int) and s <= line <= e for s, e in ranges
            ):
                continue
            value = entry["value"]
            if value in blob or value in dropped:
                continue
            message = (
                f"record {rec_id}: ledger value '{value}' ({entry.get('kind')}, line {line}) "
                "missing — copy it into the record or list it in dropped_values"
            )
            (errors if strict else warnings).append(message)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def range_text(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def parse_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_no}: invalid JSON: {exc}")
                continue
            if not isinstance(obj, dict):
                errors.append(f"{path}:{line_no}: JSONL record must be an object")
                continue
            obj["_jsonl_line"] = line_no
            records.append(obj)
    return records, errors


def validate_range(value: Any, line_count: int, label: str, errors: list[str]) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        errors.append(f"{label}: range must be an object")
        return None
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        errors.append(f"{label}: range start/end must be integers")
        return None
    if start < 1 or end < start or end > line_count:
        errors.append(f"{label}: invalid range {start}-{end} for source with {line_count} lines")
        return None
    return start, end


def validate_record(
    record: dict[str, Any],
    source_hash: str,
    source_lines: list[str],
    require_evidence: bool,
    match_mode: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    rec_id = str(record.get("id", f"line-{record.get('_jsonl_line', '?')}"))
    prefix = f"record {rec_id}"

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in record:
            errors.append(f"{prefix}: missing required field '{field}'")
            continue
        if not isinstance(record[field], expected_type):
            errors.append(f"{prefix}: field '{field}' must be {expected_type.__name__}")

    if isinstance(record.get("kind"), str) and record["kind"] not in ALLOWED_KINDS:
        errors.append(f"{prefix}: kind '{record['kind']}' is not allowed")

    if isinstance(record.get("source_sha256"), str) and record["source_sha256"] != source_hash:
        errors.append(f"{prefix}: source_sha256 does not match source file")

    line_count = len(source_lines)
    ranges = record.get("source_ranges")
    valid_ranges: list[tuple[int, int]] = []
    if isinstance(ranges, list):
        if not ranges:
            errors.append(f"{prefix}: source_ranges must not be empty")
        for index, item in enumerate(ranges):
            parsed = validate_range(item, line_count, f"{prefix}.source_ranges[{index}]", errors)
            if parsed:
                valid_ranges.append(parsed)

    evidence = record.get("evidence_quotes")
    if isinstance(evidence, list):
        if require_evidence and not evidence:
            errors.append(f"{prefix}: evidence_quotes must not be empty when --require-evidence is used")
        elif not evidence:
            warnings.append(f"{prefix}: no evidence quotes")

        for index, quote_obj in enumerate(evidence):
            quote_label = f"{prefix}.evidence_quotes[{index}]"
            if not isinstance(quote_obj, dict):
                errors.append(f"{quote_label}: must be an object")
                continue
            quote = quote_obj.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                errors.append(f"{quote_label}: quote must be a non-empty string")
                continue
            parsed = validate_range(quote_obj.get("source_range"), line_count, quote_label, errors)
            if not parsed:
                continue
            start, end = parsed
            source_slice = range_text(source_lines, start, end)
            if match_mode == "exact":
                found = quote in source_slice
            else:
                found = normalize_ws(quote) in normalize_ws(source_slice)
            if not found:
                errors.append(f"{quote_label}: quote not found in declared source_range {start}-{end}")

    for field in [
        "user_requests",
        "assistant_conclusions",
        "files_analyzed",
        "commands_or_tools",
        "decisions",
        "risks_or_open_questions",
    ]:
        value = record.get(field)
        if isinstance(value, list) and not value:
            warnings.append(f"{prefix}: '{field}' is empty")

    for field in OPTIONAL_LIST_FIELDS:
        if field in record and not isinstance(record[field], list):
            errors.append(f"{prefix}: field '{field}' must be list when present")

    if valid_ranges:
        first_lines = [start for start, _ in valid_ranges]
        if first_lines != sorted(first_lines):
            warnings.append(f"{prefix}: source_ranges are not sorted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path, help="Curated JSONL file")
    parser.add_argument("--source", type=Path, required=True, help="Source transcript")
    parser.add_argument("--require-evidence", action="store_true", help="Fail records without evidence quotes")
    parser.add_argument(
        "--match-mode",
        choices=["normalized", "exact"],
        default="normalized",
        help="How evidence quotes are matched against source ranges",
    )
    parser.add_argument(
        "--values-ledger",
        type=Path,
        help="chunks_manifest.json with per-chunk values_ledger; enables anti-genericization coverage check",
    )
    parser.add_argument(
        "--strict-values",
        action="store_true",
        help="Treat unaccounted ledger values as errors instead of warnings",
    )
    args = parser.parse_args()

    source_path = args.source.expanduser().resolve()
    jsonl_path = args.jsonl.expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"source file not found: {source_path}")
    if not jsonl_path.is_file():
        raise SystemExit(f"jsonl file not found: {jsonl_path}")

    source_hash = sha256_path(source_path)
    source_lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    records, errors = parse_jsonl(jsonl_path)
    warnings: list[str] = []
    ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for record in records:
        rec_id = record.get("id")
        if isinstance(rec_id, str):
            if rec_id in ids:
                duplicate_ids.add(rec_id)
            ids.add(rec_id)
        validate_record(
            record,
            source_hash,
            source_lines,
            args.require_evidence,
            args.match_mode,
            errors,
            warnings,
        )

    for rec_id in sorted(duplicate_ids):
        errors.append(f"duplicate record id: {rec_id}")

    if args.values_ledger:
        ledger_path = args.values_ledger.expanduser().resolve()
        if not ledger_path.is_file():
            raise SystemExit(f"values ledger not found: {ledger_path}")
        ledger = load_values_ledger(ledger_path)
        check_values_coverage(records, ledger, args.strict_values, errors, warnings)

    result = {
        "jsonl": str(jsonl_path),
        "source": str(source_path),
        "source_sha256": source_hash,
        "record_count": len(records),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
