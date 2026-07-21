#!/usr/bin/env python3
"""Small JSONL tracing primitive with correlation fields and secret redaction."""

from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
_SECRET_VALUE = re.compile(r"\b(?:Bearer\s+[A-Za-z0-9._~+/=-]+|sk-[A-Za-z0-9_-]{8,})\b", re.I)
_KINDS = {"SPAN_START", "SPAN_END", "EVENT", "ERROR"}


class TraceValidationError(ValueError):
    pass


def redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(child_key): redact(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, tuple):
        return [redact(child) for child in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


def validate_record(record: Any) -> None:
    if not isinstance(record, dict):
        raise TraceValidationError("trace record must be an object")
    allowed = {"schema_version", "trace_id", "span_id", "parent_span_id", "run_id", "node_id", "agent_id", "kind", "name", "timestamp", "attributes"}
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise TraceValidationError(f"unknown trace fields: {', '.join(unknown)}")
    for field in ("trace_id", "span_id", "run_id", "name", "timestamp"):
        if not isinstance(record.get(field), str) or not record[field]:
            raise TraceValidationError(f"{field} must be a non-empty string")
    try:
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise TraceValidationError("timestamp must be a valid timezone-aware RFC3339 value") from exc
    if record.get("schema_version") != "1.0":
        raise TraceValidationError("schema_version must be 1.0")
    if record.get("kind") not in _KINDS:
        raise TraceValidationError(f"invalid trace kind {record.get('kind')!r}")
    if not isinstance(record.get("attributes"), dict):
        raise TraceValidationError("attributes must be an object")
    for field in ("parent_span_id", "node_id", "agent_id"):
        if field in record and record[field] is not None and not isinstance(record[field], str):
            raise TraceValidationError(f"{field} must be string|null")


def prepare_record(record: dict[str, Any]) -> dict[str, Any]:
    validate_record(record)
    safe = dict(record)
    safe["attributes"] = redact(record["attributes"])
    return safe


def append_trace(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    safe = prepare_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return safe


def correlated(records: list[dict[str, Any]], run_id: str, node_id: str | None = None, agent_id: str | None = None) -> list[dict[str, Any]]:
    return [
        record for record in records
        if record.get("run_id") == run_id
        and (node_id is None or record.get("node_id") == node_id)
        and (agent_id is None or record.get("agent_id") == agent_id)
    ]
