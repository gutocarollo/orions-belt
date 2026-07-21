"""Fail-closed raw-to-canonical corpus pipeline.

Raw bytes are read as data only. This module never imports, evaluates, shells out to, or follows
instructions found in corpus content. Canonical promotion requires explicit review decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0.0"
ALLOWED_SUFFIXES = {".md", ".txt", ".html", ".htm", ".json"}
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(r"\b(ignore|disregard)\b.{0,80}\b(previous|system|developer)\b.{0,40}\binstruction", re.I | re.S)),
    ("system_prompt_request", re.compile(r"\b(system prompt|developer message|hidden instructions?)\b", re.I)),
    ("tool_execution_request", re.compile(r"\b(call|invoke|use|execute|run)\b.{0,50}\b(tool|shell|command|terminal|bash)\b", re.I | re.S)),
    ("secret_exfiltration", re.compile(r"\b(exfiltrat|steal|reveal|print|send)\w*\b.{0,60}\b(secret|token|password|credential|api[_ -]?key)\b", re.I | re.S)),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_id(relative_path: str, digest: str) -> str:
    value = f"{relative_path}\x1f{digest}".encode("utf-8")
    return f"source:{hashlib.sha256(value).hexdigest()[:24]}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_source_url(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _read_source_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(isinstance(value, dict) for value in payload.values()):
        raise ValueError("source map must be an object keyed by relative path")
    return payload


def discover_source_map(raw_dir: Path) -> dict[str, dict[str, Any]]:
    """Extract only explicit Firecrawl provenance, never guessed URLs."""

    root = raw_dir.resolve()
    discovered: dict[str, dict[str, Any]] = {}
    index_pattern = re.compile(r"\]\(([^)]+)\)\s+(?:—|-)\s+(https?://\S+)")
    for index_path in sorted(root.rglob("_INDEX.md")):
        try:
            text = index_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for target, url in index_pattern.findall(text):
            target_path = (index_path.parent / target).resolve()
            try:
                relative = target_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if target_path.is_file() and _valid_source_url(url):
                discovered[relative] = {
                    "source_url": url.rstrip(".,;"),
                    "final_url": url.rstrip(".,;"),
                    "source_url_method": "index_link",
                }
    for json_path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        source_url = metadata.get("sourceURL") if isinstance(metadata, dict) else None
        final_url = metadata.get("url", source_url) if isinstance(metadata, dict) else None
        if _valid_source_url(source_url) and source_url:
            discovered[json_path.relative_to(root).as_posix()] = {
                "source_url": source_url,
                "final_url": final_url if _valid_source_url(final_url) else source_url,
                "source_url_method": "embedded_metadata",
            }
    return discovered


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_manifest(
    raw_dir: Path, source_map_path: Path | None = None, discover_sources: bool = False
) -> dict[str, Any]:
    root = raw_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"raw directory does not exist: {raw_dir}")
    source_map = discover_source_map(root) if discover_sources else {}
    supplied_source_map = _read_source_map(source_map_path)
    for relative, origin in supplied_source_map.items():
        source_map[relative] = {**origin, "source_url_method": origin.get("source_url_method", "supplied")}
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"raw corpus contains a symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest = _sha256(data)
        origin = source_map.get(relative, {})
        source_url = origin.get("source_url")
        final_url = origin.get("final_url", source_url)
        if not _valid_source_url(source_url) or not _valid_source_url(final_url):
            raise ValueError(f"source map has invalid HTTP(S) URL for {relative}")
        records.append(
            {
                "id": _source_id(relative, digest),
                "path": relative,
                "sha256": digest,
                "bytes": len(data),
                "source_url": source_url,
                "final_url": final_url,
                "source_url_method": origin.get("source_url_method"),
                "license": origin.get("license"),
                "trust_label": "raw_untrusted",
            }
        )
    unknown = set(source_map) - {record["path"] for record in records}
    if unknown:
        raise ValueError(f"source map references missing raw files: {', '.join(sorted(unknown))}")
    return {"schema_version": SCHEMA_VERSION, "stage": "manifest", "generated_at": _now(), "records": records}


def _content_reasons(path: Path, data: bytes, max_bytes: int) -> list[str]:
    reasons: list[str] = []
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        reasons.append("unsupported_file_type")
    if len(data) > max_bytes:
        reasons.append("file_too_large")
    if b"\x00" in data:
        reasons.append("binary_or_nul_content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return reasons + ["invalid_utf8"]
    for label, pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(f"prompt_injection:{label}")
    return sorted(set(reasons))


def validate_manifest(
    raw_dir: Path, manifest: Mapping[str, Any], max_bytes: int = DEFAULT_MAX_BYTES
) -> dict[str, Any]:
    if manifest.get("stage") != "manifest" or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("input is not a supported manifest")
    root = raw_dir.resolve()
    records: list[dict[str, Any]] = []
    for source in manifest.get("records", []):
        relative = Path(str(source["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe manifest path: {relative}")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            reasons = ["source_missing_or_symlink"]
        else:
            data = path.read_bytes()
            reasons = _content_reasons(path, data, max_bytes)
            if _sha256(data) != source.get("sha256") or len(data) != source.get("bytes"):
                reasons.append("integrity_mismatch")
        record = dict(source)
        record["status"] = "quarantined" if reasons else "accepted"
        record["reasons"] = sorted(set(reasons))
        record["trust_label"] = "raw_untrusted" if reasons else "validated_untrusted"
        records.append(record)
    return {"schema_version": SCHEMA_VERSION, "stage": "validated", "generated_at": _now(), "records": records}


def summarize_validation(validated: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable machine-readable accounting report without corpus content."""

    if validated.get("stage") != "validated" or validated.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("input is not a supported validated corpus")
    records = validated.get("records", [])
    status_counts = Counter(str(record.get("status", "missing")) for record in records)
    reason_counts = Counter(
        str(reason) for record in records for reason in record.get("reasons", [])
    )
    suffix_counts = Counter(Path(str(record["path"])).suffix.lower() or "<none>" for record in records)
    canonical = json.dumps(validated, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_stage": "validated",
        "validated_sha256": _sha256(canonical),
        "total_records": len(records),
        "total_bytes": sum(int(record.get("bytes", 0)) for record in records),
        "accepted": status_counts["accepted"],
        "quarantined": status_counts["quarantined"],
        "with_source_url": sum(bool(record.get("source_url")) for record in records),
        "missing_source_url": sum(not bool(record.get("source_url")) for record in records),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "promotion_performed": False,
    }


def curate(validated: Mapping[str, Any], decisions: Mapping[str, Any]) -> dict[str, Any]:
    """Attach human-authored claims; raw text is never promoted or interpreted here."""

    if validated.get("stage") != "validated":
        raise ValueError("input is not a validated corpus")
    decision_map = decisions.get("decisions")
    if not isinstance(decision_map, dict):
        raise ValueError("decisions must contain an object named decisions")
    records: list[dict[str, Any]] = []
    accepted_paths = {record["path"] for record in validated.get("records", []) if record.get("status") == "accepted"}
    unknown = set(decision_map) - accepted_paths
    if unknown:
        raise ValueError(f"decisions reference non-accepted sources: {', '.join(sorted(unknown))}")
    for source in validated.get("records", []):
        if source.get("status") != "accepted" or source["path"] not in decision_map:
            continue
        decision = decision_map[source["path"]]
        reviewer = decision.get("reviewed_by") if isinstance(decision, dict) else None
        claims = decision.get("claims") if isinstance(decision, dict) else None
        if not reviewer or not isinstance(claims, list) or not claims:
            raise ValueError(f"curation for {source['path']} requires reviewed_by and non-empty claims")
        for claim in claims:
            if not isinstance(claim, dict) or not claim.get("text") or not claim.get("citation"):
                raise ValueError(f"every claim for {source['path']} requires text and citation")
        record = dict(source)
        record.update({"trust_label": "reviewed", "status": "approved", "reviewed_by": reviewer, "claims": claims})
        records.append(record)
    return {"schema_version": SCHEMA_VERSION, "stage": "curated", "generated_at": _now(), "records": records}


def promote(curated: Mapping[str, Any], approvals: Mapping[str, Any]) -> dict[str, Any]:
    """Promote only explicitly approved reviewed records to canonical knowledge."""

    if curated.get("stage") != "curated":
        raise ValueError("input is not a curated corpus")
    approved_ids = approvals.get("approved_ids")
    approver = approvals.get("approved_by")
    if not isinstance(approved_ids, list) or not approver:
        raise ValueError("promotion requires approved_ids and approved_by")
    available = {record["id"]: record for record in curated.get("records", [])}
    unknown = set(approved_ids) - set(available)
    if unknown:
        raise ValueError(f"approval references unknown curated IDs: {', '.join(sorted(unknown))}")
    records = []
    for source_id in approved_ids:
        record = dict(available[source_id])
        if record.get("trust_label") != "reviewed" or record.get("status") != "approved":
            raise ValueError(f"source is not reviewed and approved: {source_id}")
        record["trust_label"] = "canonical"
        record["canonical_approved_by"] = approver
        records.append(record)
    return {"schema_version": SCHEMA_VERSION, "stage": "canonical", "generated_at": _now(), "records": records}
