#!/usr/bin/env python3
"""Validation and hashing for the evidence/provenance manifest."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_AGENT_TYPES = {"human", "software", "organization"}
_ACTIVITY_TYPES = {"command", "test", "capture", "transform", "review"}
_ENTITY_TYPES = {"artifact", "source", "screenshot", "log", "test-result"}
_TRUST = {"trusted", "validated", "untrusted", "quarantined"}
_CLAIM_STATUS = {"PASS", "FAIL", "UNVERIFIED"}


class EvidenceValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _time(value: Any, path: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{path}: expected RFC3339 string")
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: invalid RFC3339 timestamp {value!r}")
        return None


def _unique(items: Any, family: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        errors.append(f"{family}: expected array")
        return {}
    found: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{family}[{index}]: expected object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not _ID.fullmatch(item_id):
            errors.append(f"{family}[{index}].id: invalid identifier")
        elif item_id in found:
            errors.append(f"{family}: duplicate id {item_id!r}")
        else:
            found[item_id] = item
    return found


def _reject_extra(item: dict[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(set(item) - allowed):
        errors.append(f"{path}.{field}: additional property is not allowed")


def _local_uri(uri: str, base_dir: Path) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        candidate = Path(parsed.path)
    elif parsed.scheme:
        return None
    else:
        candidate = Path(uri)
    resolved = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError("local entity URI escapes manifest base directory") from exc
    return resolved


def validate_manifest(manifest: Any, base_dir: Path | None = None, verify_files: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["$: expected object"]
    _reject_extra(
        manifest,
        {"schema_version", "report_id", "title", "git_sha", "recorded_at", "valid_at", "agents", "activities", "entities", "claims"},
        "$", errors,
    )
    if manifest.get("schema_version") != "1.0":
        errors.append("schema_version: expected '1.0'")
    for field in ("report_id", "title"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            errors.append(f"{field}: required non-empty string")
    if not isinstance(manifest.get("git_sha"), str) or not _GIT_SHA.fullmatch(manifest["git_sha"]):
        errors.append("git_sha: expected 7-64 lowercase hexadecimal characters")
    _time(manifest.get("recorded_at"), "recorded_at", errors)
    _time(manifest.get("valid_at"), "valid_at", errors)

    agents = _unique(manifest.get("agents"), "agents", errors)
    activities = _unique(manifest.get("activities"), "activities", errors)
    entities = _unique(manifest.get("entities"), "entities", errors)
    claims = _unique(manifest.get("claims"), "claims", errors)

    for item_id, agent in agents.items():
        _reject_extra(agent, {"id", "type", "name", "version"}, f"agents.{item_id}", errors)
        if agent.get("type") not in _AGENT_TYPES:
            errors.append(f"agents.{item_id}.type: invalid")
        if not isinstance(agent.get("name"), str) or not agent["name"]:
            errors.append(f"agents.{item_id}.name: required")

    for item_id, entity in entities.items():
        _reject_extra(entity, {"id", "type", "uri", "sha256", "media_type", "trust", "recorded_at", "route", "theme"}, f"entities.{item_id}", errors)
        if entity.get("type") not in _ENTITY_TYPES:
            errors.append(f"entities.{item_id}.type: invalid")
        if entity.get("trust") not in _TRUST:
            errors.append(f"entities.{item_id}.trust: invalid")
        if not isinstance(entity.get("sha256"), str) or not _SHA256.fullmatch(entity["sha256"]):
            errors.append(f"entities.{item_id}.sha256: expected lowercase SHA-256")
        for field in ("uri", "media_type"):
            if not isinstance(entity.get(field), str) or not entity[field]:
                errors.append(f"entities.{item_id}.{field}: required")
        _time(entity.get("recorded_at"), f"entities.{item_id}.recorded_at", errors)
        if entity.get("type") == "screenshot" and (not entity.get("route") or not entity.get("theme")):
            errors.append(f"entities.{item_id}: screenshot requires route and theme")
        if verify_files and base_dir and isinstance(entity.get("uri"), str):
            try:
                local = _local_uri(entity["uri"], base_dir)
                if local is not None:
                    if not local.is_file():
                        errors.append(f"entities.{item_id}.uri: local file does not exist")
                    elif _SHA256.fullmatch(str(entity.get("sha256", ""))) and file_sha256(local) != entity["sha256"]:
                        errors.append(f"entities.{item_id}.sha256: local file hash mismatch")
            except ValueError as exc:
                errors.append(f"entities.{item_id}.uri: {exc}")

    for item_id, activity in activities.items():
        _reject_extra(activity, {"id", "type", "agent_id", "started_at", "ended_at", "command", "exit_code", "used", "generated"}, f"activities.{item_id}", errors)
        if activity.get("type") not in _ACTIVITY_TYPES:
            errors.append(f"activities.{item_id}.type: invalid")
        if activity.get("agent_id") not in agents:
            errors.append(f"activities.{item_id}.agent_id: unknown agent {activity.get('agent_id')!r}")
        started = _time(activity.get("started_at"), f"activities.{item_id}.started_at", errors)
        ended = _time(activity.get("ended_at"), f"activities.{item_id}.ended_at", errors)
        if started and ended and ended < started:
            errors.append(f"activities.{item_id}: ended_at precedes started_at")
        for field in ("used", "generated"):
            refs = activity.get(field)
            if not isinstance(refs, list):
                errors.append(f"activities.{item_id}.{field}: expected array")
            else:
                for ref in refs:
                    if ref not in entities:
                        errors.append(f"activities.{item_id}.{field}: unknown entity {ref!r}")
        if activity.get("type") in {"command", "test"}:
            if not isinstance(activity.get("command"), list) or not activity["command"] or not all(isinstance(part, str) for part in activity["command"]):
                errors.append(f"activities.{item_id}.command: command/test requires argv array")
            if not isinstance(activity.get("exit_code"), int) or isinstance(activity.get("exit_code"), bool):
                errors.append(f"activities.{item_id}.exit_code: command/test requires integer")

    for item_id, claim in claims.items():
        _reject_extra(claim, {"id", "statement", "status", "recorded_at", "valid_at", "activities", "entities"}, f"claims.{item_id}", errors)
        if claim.get("status") not in _CLAIM_STATUS:
            errors.append(f"claims.{item_id}.status: invalid")
        if not isinstance(claim.get("statement"), str) or not claim["statement"]:
            errors.append(f"claims.{item_id}.statement: required")
        _time(claim.get("recorded_at"), f"claims.{item_id}.recorded_at", errors)
        _time(claim.get("valid_at"), f"claims.{item_id}.valid_at", errors)
        evidence_count = 0
        for field, known in (("activities", activities), ("entities", entities)):
            refs = claim.get(field)
            if not isinstance(refs, list):
                errors.append(f"claims.{item_id}.{field}: expected array")
                continue
            evidence_count += len(refs)
            for ref in refs:
                if ref not in known:
                    errors.append(f"claims.{item_id}.{field}: unknown reference {ref!r}")
        if claim.get("status") in {"PASS", "FAIL"} and evidence_count == 0:
            errors.append(f"claims.{item_id}: verified status requires evidence references")
        if claim.get("status") == "PASS":
            for ref in claim.get("activities", []):
                activity = activities.get(ref, {})
                if activity.get("type") in {"command", "test"} and activity.get("exit_code") != 0:
                    errors.append(f"claims.{item_id}: PASS references failed activity {ref!r}")
            for ref in claim.get("entities", []):
                if entities.get(ref, {}).get("trust") == "quarantined":
                    errors.append(f"claims.{item_id}: PASS references quarantined entity {ref!r}")
    return errors


def assert_valid_manifest(manifest: Any, base_dir: Path | None = None, verify_files: bool = False) -> None:
    errors = validate_manifest(manifest, base_dir, verify_files)
    if errors:
        raise EvidenceValidationError(errors)
