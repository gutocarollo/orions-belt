#!/usr/bin/env python3
"""Evidence verification for CONTEXT-DELIVERY.

A hash proves immutability, not execution. This module therefore binds every
required method and runtime predicate to successful hook receipts produced by
the configured context agent, verifies actual pre/post ordering, and derives
CodeGraph freshness from the provider's status response.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from context_receipt_fields import DEFINITION_ID_RE
from context_provider_probe import ProviderProbeError, parse_codegraph_status


class ContextEvidenceError(ValueError):
    """Context evidence is missing, stale, inconsistent or untrusted."""


COMPLETENESS_RE = re.compile(
    r"\b(all|every|complete|completely|exhaustive|exhaustively|todos|todas|cada|completo|completa|exaustivo|exaustiva)\b",
    re.IGNORECASE,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContextEvidenceError(message)


def _safe_file(root: Path, relative: str, allowed_root: str) -> Path:
    _require(bool(relative), "evidence path is empty")
    path = (root / relative).resolve()
    boundary = (root / allowed_root).resolve()
    _require(path == boundary or boundary in path.parents, f"evidence path escapes {allowed_root}: {relative}")
    _require(path.is_file(), f"evidence file does not exist: {relative}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprinted_path(relative: str) -> bool:
    return not (
        relative == ".git"
        or relative.startswith(".git/")
        or relative == ".harness/runs"
        or relative.startswith(".harness/runs/")
        or relative in {".harness/council-active", ".harness/council-active.required-next"}
    )


def repository_fingerprint(root: Path) -> str:
    """Hash HEAD plus repository file identities/content, excluding runtime state."""
    resolved = root.resolve(strict=True)
    digest = hashlib.sha256(b"orions-repository-fingerprint-v1\0")
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=resolved, text=True, stderr=subprocess.DEVNULL
        ).strip()
        raw_paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
            cwd=resolved,
        )
        paths = sorted(
            value.decode("utf-8", errors="surrogateescape")
            for value in raw_paths.split(b"\0")
            if value
        )
    except (OSError, subprocess.CalledProcessError):
        head = "NO_GIT_HEAD"
        paths = []
        for directory, names, files in os.walk(resolved, followlinks=False):
            relative_directory = Path(directory).relative_to(resolved).as_posix()
            names[:] = [
                name for name in names
                if _fingerprinted_path(
                    name if relative_directory == "." else f"{relative_directory}/{name}"
                )
            ]
            for name in files:
                relative = name if relative_directory == "." else f"{relative_directory}/{name}"
                if _fingerprinted_path(relative):
                    paths.append(relative)
        paths.sort()
    digest.update(head.encode("ascii", errors="replace") + b"\0")
    for relative in paths:
        if not _fingerprinted_path(relative):
            continue
        path = resolved / relative
        metadata = path.lstat()
        digest.update(relative.encode("utf-8", errors="surrogateescape") + b"\0")
        digest.update(oct(stat.S_IFMT(metadata.st_mode) | stat.S_IMODE(metadata.st_mode)).encode() + b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(_sha256(path).encode())
        else:
            digest.update(b"SPECIAL")
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_file(root: Path, receipt: dict[str, Any], allowed_root: str) -> Path:
    path = _safe_file(root, str(receipt.get("path", "")), allowed_root)
    expected = str(receipt.get("sha256", ""))
    _require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid sha256 for {receipt.get('path')}")
    _require(_sha256(path) == expected, f"evidence hash mismatch: {receipt.get('path')}")
    return path


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContextEvidenceError(f"{path}:{number}: invalid JSONL: {exc}") from exc
        _require(isinstance(item, dict), f"{path}:{number}: record must be an object")
        records.append(item)
    return records


MODEL_FAMILY_ALIASES = {"haiku", "sonnet", "opus", "luna", "terra", "sol", "fable"}


def _model_matches(configured: str, observed: str) -> bool:
    """Match an explicit configured model to a runtime-resolved model id.

    Claude commonly resolves family aliases such as ``sonnet`` to a dated
    provider id. Family matching remains strict: ``sonnet`` cannot authorize
    ``opus``. Non-family model names require exact normalized equality.
    """
    configured_norm = re.sub(r"[^a-z0-9]+", "-", configured.lower()).strip("-")
    observed_norm = re.sub(r"[^a-z0-9]+", "-", observed.lower()).strip("-")
    if configured_norm == observed_norm:
        return True
    if configured_norm in MODEL_FAMILY_ALIASES:
        return configured_norm in observed_norm.split("-")
    return False


def _verify_lifecycle(root: Path, delivery: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    path = _verify_file(root, delivery["lifecycle_receipt"], ".harness/runs/subagents")
    records = _jsonl(path)
    agent_id = delivery["agent_id"]
    agent_type = delivery["agent_type"]
    runtime = delivery["runtime"]
    run_id = delivery["run_id"]
    session_id = delivery["session_id"]
    fingerprint = delivery["repository_fingerprint"]
    matching = [
        item for item in records
        if item.get("agent_id") == agent_id
        and item.get("agent_type") == agent_type
        and item.get("runtime") == runtime
        and item.get("run_id") == run_id
        and item.get("session_id") == session_id
        and item.get("repository_fingerprint") == fingerprint
    ]
    _require(any(item.get("event") == "SubagentStart" for item in matching), "missing matching SubagentStart receipt")
    _require(any(item.get("event") == "SubagentStop" for item in matching), "missing matching SubagentStop receipt")
    configured = {str(item.get("configured_model")) for item in matching if item.get("configured_model")}
    observed = {
        str(item.get("model")) for item in matching
        if item.get("model") and item.get("event") in {"SubagentStart", "AgentToolResult", "SubagentStop"}
    }
    allowed = {str(value) for value in plan.get("allowed_models", []) if str(value)}
    _require(bool(allowed), "CONTEXT-PLAN allowed_models must be non-empty")
    _require(
        any(_model_matches(candidate, str(delivery["model"])) for candidate in allowed),
        f"delivery model is not allowed: {delivery['model']}",
    )
    _require(
        not configured or all(any(_model_matches(candidate, value) for candidate in allowed) for value in configured),
        f"configured subagent model is not allowed: {sorted(configured)}",
    )
    _require(bool(observed), f"{runtime} context agent lacks an observed runtime model")
    _require(
        all(any(_model_matches(candidate, value) for candidate in allowed) for value in observed),
        f"observed runtime model is not allowed: {sorted(observed)}",
    )
    _require(
        any(_model_matches(str(delivery["model"]), value) or _model_matches(value, str(delivery["model"])) for value in observed),
        "delivery model differs from observed runtime model",
    )
    allowed_types = {str(value) for value in plan.get("allowed_agent_types", []) if str(value)}
    _require(bool(allowed_types), "CONTEXT-PLAN allowed_agent_types must be non-empty")
    _require(agent_type in allowed_types, f"agent_type is not authorized by CONTEXT-PLAN: {agent_type}")
    transcripts = {
        str(item.get("agent_transcript_path") or item.get("transcript_path"))
        for item in matching
        if item.get("agent_transcript_path") or item.get("transcript_path")
    }
    sessions = {str(item.get("session_id") or "") for item in matching}
    _require(sessions == {session_id}, "context lifecycle receipt must match delivery session_id")
    transcript_records = [item for item in matching if item.get("source") == "codex-transcript-v1"]
    if transcript_records:
        _require(runtime == "codex", "transcript-derived lifecycle receipts are Codex-only")
        transcript_paths = {str(item.get("agent_transcript_path") or "") for item in transcript_records}
        transcript_hashes = {str(item.get("transcript_sha256") or "") for item in transcript_records}
        _require(len(transcript_paths) == 1 and "" not in transcript_paths, "Codex lifecycle must bind one child transcript")
        _require(len(transcript_hashes) == 1 and re.fullmatch(r"[0-9a-f]{64}", next(iter(transcript_hashes))) is not None, "Codex lifecycle transcript hash is invalid")
        transcript = Path(next(iter(transcript_paths))).resolve()
        _require(transcript.is_file(), f"Codex lifecycle transcript is absent: {transcript}")
        _require(_sha256(transcript) == next(iter(transcript_hashes)), "Codex lifecycle transcript hash mismatch")
        transcript_events = _jsonl(transcript)
        _require(bool(transcript_events) and transcript_events[0].get("type") == "session_meta", "Codex transcript lacks session_meta")
        meta = transcript_events[0].get("payload") or {}
        _require(meta.get("id") == agent_id, "Codex transcript agent id differs from lifecycle receipt")
        _require(meta.get("session_id") in sessions, "Codex transcript parent session differs from lifecycle receipt")
        _require(meta.get("agent_role") == agent_type, "Codex transcript agent role differs from lifecycle receipt")
        _require(any(item.get("type") == "event_msg" and (item.get("payload") or {}).get("type") == "task_complete" for item in transcript_events), "Codex transcript lacks task_complete")
        resolved_models = {
            str((item.get("payload") or {}).get("model"))
            for item in transcript_events if item.get("type") == "turn_context" and (item.get("payload") or {}).get("model")
        }
        _require(resolved_models == observed, "Codex transcript model differs from lifecycle receipt")
    return {"records": matching, "transcripts": transcripts, "observed_models": observed, "sessions": sessions}


def _verify_tools(root: Path, delivery: dict[str, Any], lifecycle: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = _verify_file(root, delivery["tool_receipt"], ".harness/runs/context-tools")
    records = _jsonl(path)
    agent_id = delivery["agent_id"]
    transcripts = lifecycle["transcripts"]
    runtime = delivery["runtime"]
    agent_type = delivery["agent_type"]
    model = delivery["model"]
    context_records = [
        item for item in records
        if item.get("runtime") == runtime
        and item.get("run_id") == delivery["run_id"]
        and item.get("session_id") == delivery["session_id"]
        and item.get("repository_fingerprint") == delivery["repository_fingerprint"]
        and (not item.get("agent_type") or item.get("agent_type") == agent_type)
        and (
            not item.get("model")
            or _model_matches(str(item.get("model")), model)
            or _model_matches(model, str(item.get("model")))
        )
        and (
            item.get("agent_id") == agent_id
            or (item.get("transcript_path") and str(item.get("transcript_path")) in transcripts)
        )
    ]
    coordinator_status_records = [
        item for item in records
        if item.get("runtime") == runtime
        and item.get("run_id") == delivery["run_id"]
        and item.get("repository_fingerprint") == delivery["repository_fingerprint"]
        and str(item.get("session_id") or "") in lifecycle["sessions"]
        and not item.get("agent_id")
        and not item.get("agent_type")
        and item.get("methods") == ["codegraph-status"]
    ]
    matching = context_records + coordinator_status_records
    _require(context_records, "tool receipt has no calls attributable to the context agent")
    for item in context_records:
        if item.get("source") != "codex-transcript-v1":
            continue
        _require(runtime == "codex", "transcript-derived tool receipts are Codex-only")
        transcript = str(item.get("transcript_path") or "")
        _require(transcript in transcripts, "Codex tool receipt transcript differs from lifecycle receipt")
        lifecycle_hashes = {
            str(record.get("transcript_sha256") or "")
            for record in lifecycle["records"] if record.get("source") == "codex-transcript-v1"
        }
        _require(str(item.get("transcript_sha256") or "") in lifecycle_hashes, "Codex tool receipt transcript hash differs from lifecycle receipt")
    calls: dict[str, dict[str, Any]] = {}
    for item in matching:
        call_id = str(item.get("tool_use_id") or "")
        _require(bool(call_id), "tool receipt contains a call without tool_use_id")
        state = calls.setdefault(call_id, {"pre": None, "post": None, "failure": None})
        event = item.get("event")
        key = {"PreToolUse": "pre", "PostToolUse": "post", "PostToolUseFailure": "failure"}.get(event)
        _require(key is not None, f"unknown tool receipt event: {event}")
        _require(state[key] is None, f"duplicate {event} for tool_use_id: {call_id}")
        state[key] = item
    successful: dict[str, dict[str, Any]] = {}
    for call_id, state in calls.items():
        pre, post, failure = state["pre"], state["post"], state["failure"]
        _require(pre is not None, f"tool call {call_id} lacks PreToolUse receipt")
        _require(not (post and failure), f"tool call {call_id} has both success and failure receipts")
        if post is None:
            continue
        for item in (pre, post):
            _require(bool(item.get("tool_name")), f"tool receipt {call_id} lacks tool_name")
            _require(re.fullmatch(r"[0-9a-f]{64}", str(item.get("input_sha256") or "")) is not None, f"tool receipt {call_id} lacks input hash")
        _require(pre.get("tool_name") == post.get("tool_name"), f"tool call {call_id} tool_name changed between pre/post receipts")
        _require(pre.get("methods") == post.get("methods"), f"tool call {call_id} method classification changed between pre/post receipts")
        _require(pre.get("input_sha256") == post.get("input_sha256"), f"tool call {call_id} input changed between pre/post receipts")
        _require(re.fullmatch(r"[0-9a-f]{64}", str(post.get("output_sha256") or "")) is not None, f"tool receipt {call_id} lacks output hash")
        definitions = post.get("definition_ids")
        _require(isinstance(definitions, list), f"tool receipt {call_id} lacks structured definition_ids")
        _require(len(definitions) == len(set(definitions)), f"tool receipt {call_id} duplicates definition_ids")
        _require(
            all(isinstance(value, str) and DEFINITION_ID_RE.fullmatch(value) for value in definitions),
            f"tool receipt {call_id} contains an invalid definition id",
        )
        _require(int(pre.get("seq", 0)) < int(post.get("seq", 0)), f"tool call {call_id} has invalid pre/post sequence")
        successful[call_id] = {
            "pre": pre,
            "post": post,
            "tool_name": post["tool_name"],
            "methods": post.get("methods", []),
            "pre_seq": int(pre["seq"]),
            "post_seq": int(post["seq"]),
            "response_excerpt": post.get("response_excerpt", ""),
            "input_excerpt": post.get("input_excerpt", ""),
            "definition_ids": definitions,
        }
    _require(successful, "tool receipt has no successful context-agent calls")
    return matching, successful


def _is_codegraph_status_call(call: dict[str, Any]) -> bool:
    if "codegraph-status" not in call.get("methods", []):
        return False
    tool_name = str(call.get("tool_name") or "").lower()
    tool_input = str(call.get("input_excerpt") or "").lower()
    return "status" in tool_name or re.search(r"\bcodegraph\s+status\b", tool_input) is not None


def _conditional_requirement(plan: dict[str, Any], resolutions: dict[str, dict[str, Any]]) -> set[str]:
    required = set(plan["required_methods"])
    for item in plan.get("conditional_methods", []):
        predicate = item["when_predicate"]
        resolution = resolutions.get(predicate)
        _require(resolution is not None, f"conditional method requires predicate resolution: {predicate}")
        if resolution["status"] is item["equals"]:
            required.add(item["method"])
    return required


def _verify_predicates(delivery: dict[str, Any], plan: dict[str, Any], tools: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    resolutions = delivery.get("predicate_resolutions", [])
    by_name: dict[str, dict[str, Any]] = {}
    for item in resolutions:
        predicate = item["predicate"]
        _require(predicate not in by_name, f"duplicate predicate resolution: {predicate}")
        call_ids = item.get("source_tool_call_ids", [])
        _require(call_ids, f"predicate {predicate} lacks tool-call evidence")
        for call_id in call_ids:
            _require(call_id in tools, f"predicate {predicate} references unknown tool call {call_id}")
        if predicate == "P4":
            _require(any(set(tools[call_id]["methods"]) & {"codegraph", "lsp", "rg"} for call_id in call_ids), "P4 requires graph/LSP/text evidence")
            definition_count = item.get("definition_count")
            definition_ids = item.get("definition_ids")
            _require(isinstance(definition_count, int) and definition_count >= 0, "P4 definition_count must be non-negative")
            _require(isinstance(definition_ids, list) and len(definition_ids) == definition_count, "P4 definition_ids must match definition_count")
            _require(len(set(definition_ids)) == len(definition_ids), "P4 definition_ids must be unique")
            observed_definitions = {
                value
                for call_id in call_ids
                for value in tools[call_id].get("definition_ids", [])
            }
            _require(bool(observed_definitions), "P4 definition ids require path:line locators in runtime output")
            _require(set(str(value) for value in definition_ids) == observed_definitions, "P4 definition_ids must be the complete observed definition set")
            _require(item.get("status") is (definition_count > 1), "P4 status must be derived from definition_count > 1")
        elif predicate == "P5":
            _require(len(call_ids) == 1, "P5 requires exactly one CodeGraph status call")
            call = tools[call_ids[0]]
            _require(_is_codegraph_status_call(call), "P5 requires a CodeGraph status call")
            try:
                freshness = parse_codegraph_status(call["response_excerpt"])
            except ProviderProbeError as exc:
                raise ContextEvidenceError(str(exc)) from exc
            _require(item.get("status") is freshness["index_fresh"], "P5 status differs from CodeGraph status output")
        else:
            raise ContextEvidenceError(f"unsupported runtime predicate resolution: {predicate}")
        by_name[predicate] = item
    if plan["task_shape"] == "KNOWN_SYMBOL_IMPACT":
        _require("P4" in by_name, "known-symbol impact requires runtime P4 resolution")
    planned_methods = set(plan["required_methods"]) | {item["method"] for item in plan.get("conditional_methods", [])}
    if "codegraph" in planned_methods:
        _require("P5" in by_name, "CodeGraph route requires runtime P5 freshness resolution")
    p4 = by_name.get("P4")
    if p4 and p4["status"] is True:
        conditional_lsp = any(
            item.get("method") == "lsp" and item.get("when_predicate") == "P4" and item.get("equals") is True
            for item in plan.get("conditional_methods", [])
        )
        _require(conditional_lsp or "lsp" in plan.get("required_methods", []), "P4=true requires an LSP escalation in CONTEXT-PLAN")
    return by_name


def _verify_artifacts(root: Path, delivery: dict[str, Any], plan: dict[str, Any], tools: dict[str, dict[str, Any]], resolutions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    required = _conditional_requirement(plan, resolutions)
    by_method: dict[str, dict[str, Any]] = {}
    for artifact in delivery["artifacts"]:
        method = artifact["method"]
        _require(method not in by_method, f"duplicate artifact method: {method}")
        _verify_file(root, artifact, ".harness/runs")
        receipts = artifact.get("tool_receipts", [])
        _require(isinstance(receipts, list) and receipts, f"artifact {method} has no tool_receipts")
        call_ids: list[str] = []
        for receipt in receipts:
            call_id = str(receipt.get("tool_use_id") or "")
            _require(call_id in tools, f"artifact {method} references unknown tool call: {call_id}")
            _require(method in tools[call_id]["methods"], f"tool call {call_id} does not prove method {method}")
            post = tools[call_id]["post"]
            _require(receipt.get("input_sha256") == post.get("input_sha256"), f"artifact {method} input hash differs from tool call {call_id}")
            _require(receipt.get("output_sha256") == post.get("output_sha256"), f"artifact {method} output hash differs from tool call {call_id}")
            call_ids.append(call_id)
        _require(len(call_ids) == len(set(call_ids)), f"artifact {method} duplicates a tool receipt")
        try:
            payload = json.loads((root / artifact["path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextEvidenceError(f"artifact {method} must be a JSON object: {exc}") from exc
        _require(isinstance(payload, dict), f"artifact {method} must be a JSON object")
        _require(payload.get("method") == method, f"artifact {method} payload method differs")
        _require(payload.get("tool_receipts") == receipts, f"artifact {method} payload does not embed exact tool receipts")
        item = dict(artifact)
        item["tool_call_ids"] = call_ids
        by_method[method] = item
    missing = sorted(method for method in required if method not in by_method)
    _require(not missing, f"missing artifacts for required methods: {missing}")

    first_pre = {method: min(tools[call_id]["pre_seq"] for call_id in by_method[method]["tool_call_ids"]) for method in required}
    last_post = {method: max(tools[call_id]["post_seq"] for call_id in by_method[method]["tool_call_ids"]) for method in required}
    for edge in plan.get("dependency_edges", []):
        before, after = edge["before"], edge["after"]
        if before in required and after in required:
            _require(last_post[before] < first_pre[after], f"actual tool order violates {before} -> {after}")
    return by_method


def _verify_provider(delivery: dict[str, Any], plan: dict[str, Any], tools: dict[str, dict[str, Any]], resolutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    planned_methods = set(plan["required_methods"]) | {item["method"] for item in plan.get("conditional_methods", [])}
    if "codegraph" not in planned_methods:
        _require(delivery["provider_state"].get("status") == "NOT_REQUIRED", "non-graph route must declare provider NOT_REQUIRED")
        return {"provider": "NOT_REQUIRED", "status": "NOT_REQUIRED", "index_fresh": True, "pending_changes": 0, "provider_version": "not-required"}
    provider = delivery["provider_state"]
    source_id = str(provider.get("source_tool_call_id") or "")
    _require(source_id in tools, "CodeGraph provider_state is not bound to a successful tool call")
    p5 = resolutions.get("P5")
    _require(p5 is not None and p5.get("source_tool_call_ids") == [source_id], "provider_state must use the same status call as P5")
    record = tools[source_id]
    _require(_is_codegraph_status_call(record), "provider_state source is not a CodeGraph status call")
    try:
        derived = parse_codegraph_status(record["response_excerpt"])
    except ProviderProbeError as exc:
        raise ContextEvidenceError(str(exc)) from exc
    for key in ("provider", "status", "index_fresh", "pending_changes", "provider_version"):
        _require(provider.get(key) == derived.get(key), f"provider_state.{key} differs from runtime status receipt")
    _require(derived["index_fresh"] is True and derived["pending_changes"] == 0, "CodeGraph index is stale or has pending changes")
    return derived


def _verify_coverage(delivery: dict[str, Any], plan: dict[str, Any], root: Path, tools: dict[str, dict[str, Any]]) -> None:
    coverage = delivery["coverage"]
    for key in ("eligible_files", "analyzed_files", "candidates", "confirmed", "false_positives", "unresolved"):
        value = coverage.get(key)
        _require(isinstance(value, int) and value >= 0, f"coverage.{key} must be a non-negative integer")
    identity_fields = {
        "eligible_files": "eligible_paths",
        "analyzed_files": "analyzed_paths",
        "candidates": "candidate_ids",
        "confirmed": "confirmed_candidate_ids",
        "false_positives": "false_positive_candidate_ids",
        "unresolved": "unresolved_candidate_ids",
    }
    identities: dict[str, list[str]] = {}
    for count_field, identity_field in identity_fields.items():
        values = coverage.get(identity_field)
        _require(isinstance(values, list), f"coverage.{identity_field} must be an array")
        normalized = [str(value) for value in values]
        _require(all(normalized), f"coverage.{identity_field} cannot contain empty identities")
        _require(len(normalized) == len(set(normalized)), f"coverage.{identity_field} identities must be unique")
        _require(coverage[count_field] == len(normalized), f"coverage.{count_field} must equal len({identity_field})")
        identities[identity_field] = normalized

    eligible = set(identities["eligible_paths"])
    analyzed = set(identities["analyzed_paths"])
    _require(analyzed <= eligible, "coverage.analyzed_paths must be a subset of eligible_paths")
    for relative in eligible:
        _safe_file(root, relative, ".")

    candidates = set(identities["candidate_ids"])
    confirmed = set(identities["confirmed_candidate_ids"])
    false_positives = set(identities["false_positive_candidate_ids"])
    unresolved = set(identities["unresolved_candidate_ids"])
    _require(confirmed <= candidates and false_positives <= candidates and unresolved <= candidates, "coverage classifications must reference candidate_ids")
    _require(not (confirmed & false_positives or confirmed & unresolved or false_positives & unresolved), "coverage candidate classifications must be disjoint")

    source_ids = coverage.get("source_tool_call_ids")
    _require(isinstance(source_ids, list) and source_ids, "coverage requires source_tool_call_ids")
    for call_id in source_ids:
        _require(call_id in tools, f"coverage references unknown tool call {call_id}")
        _require(bool(set(tools[call_id]["methods"]) & {"canonical-docs", "rg", "targeted-read", "codegraph", "lsp"}), f"coverage source {call_id} is not a discovery/read tool")
    source_text = "\n".join(
        f"{tools[call_id].get('input_excerpt', '')}\n{tools[call_id].get('response_excerpt', '')}"
        for call_id in source_ids
    )
    for identity_field in ("eligible_paths", "analyzed_paths", "candidate_ids"):
        for identity in identities[identity_field]:
            _require(identity in source_text, f"coverage identity is absent from source tool receipts: {identity_field}={identity}")

    claim_text = "\n".join(item.get("claim", "") for item in delivery.get("claims", []))
    exhaustive = bool(plan.get("claims_completeness")) or bool(COMPLETENESS_RE.search(claim_text))
    if exhaustive:
        _require(coverage["analyzed_files"] == coverage["eligible_files"], "exhaustive claim requires analyzed_files == eligible_files")
        _require(coverage["unresolved"] == 0, "exhaustive claim requires unresolved == 0")
        _require(coverage["confirmed"] + coverage["false_positives"] == coverage["candidates"], "exhaustive claim requires every candidate classified")
        _require(confirmed | false_positives == candidates and not unresolved, "exhaustive claim requires a complete candidate identity partition")
    _require(not any(item.get("severity") in {"CRITICAL", "HIGH"} for item in delivery.get("unresolved_items", [])), "critical/high context items remain unresolved")


def _metric_int(value: Any, *names: str) -> int | None:
    if not isinstance(value, dict):
        return None
    for name in names:
        candidate = value.get(name)
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
    return None


def _verify_metrics(delivery: dict[str, Any], lifecycle: dict[str, Any], tool_count: int) -> None:
    metrics = delivery["execution_metrics"]
    source = metrics.get("source")
    _require(source in {"OBSERVED", "UNAVAILABLE"}, "execution_metrics.source must be OBSERVED or UNAVAILABLE")
    for key in ("duration_ms", "input_tokens", "output_tokens", "tool_calls"):
        _require(isinstance(metrics.get(key), int) and metrics[key] >= 0, f"execution_metrics.{key} must be non-negative")
    _require(metrics["tool_calls"] == tool_count, "execution_metrics.tool_calls differs from observed successful tool calls")

    observed_input: int | None = None
    observed_output: int | None = None
    observed_duration: int | None = None
    for item in lifecycle["records"]:
        usage = item.get("usage")
        input_value = _metric_int(usage, "input_tokens", "inputTokens", "input")
        output_value = _metric_int(usage, "output_tokens", "outputTokens", "output")
        duration = item.get("duration_ms")
        if input_value is not None:
            observed_input = input_value
        if output_value is not None:
            observed_output = output_value
        if isinstance(duration, int) and duration >= 0:
            observed_duration = duration

    if source == "UNAVAILABLE":
        _require(bool(metrics.get("reason")), "unavailable execution metrics require a reason")
        _require(metrics["duration_ms"] == 0 and metrics["input_tokens"] == 0 and metrics["output_tokens"] == 0, "UNAVAILABLE metrics must not contain unverified numbers")
        _require(observed_input is None or observed_output is None or observed_duration is None, "runtime supplied complete metrics but delivery marked them unavailable")
        return

    _require(observed_input is not None and observed_output is not None and observed_duration is not None, "OBSERVED metrics require exact lifecycle token and duration receipts")
    _require(metrics["input_tokens"] == observed_input, "execution_metrics.input_tokens differs from lifecycle receipt")
    _require(metrics["output_tokens"] == observed_output, "execution_metrics.output_tokens differs from lifecycle receipt")
    _require(metrics["duration_ms"] == observed_duration, "execution_metrics.duration_ms differs from lifecycle receipt")
    _require(not metrics.get("reason"), "OBSERVED metrics must not carry an unavailable reason")


def verify_context_delivery(
    delivery: dict[str, Any],
    plan: dict[str, Any],
    repository_root: Path,
    *,
    expected_run_id: str | None = None,
    expected_base_sha: str | None = None,
    verify_current_repository: bool = True,
) -> dict[str, Any]:
    _require(delivery.get("status") == "SATISFEITO", "CONTEXT-DELIVERY requires SATISFEITO")
    _require(delivery.get("skill") == "context-delivery", "CONTEXT-DELIVERY requires context-delivery skill")
    _require(delivery.get("plan_id") == plan.get("plan_id"), "CONTEXT-DELIVERY plan_id differs from CONTEXT-PLAN")
    run_id = str(delivery.get("run_id") or "")
    session_id = str(delivery.get("session_id") or "")
    base_sha = str(delivery.get("base_sha") or "")
    fingerprint = str(delivery.get("repository_fingerprint") or "")
    _require(bool(run_id) and re.fullmatch(r"[A-Za-z0-9_.-]+", run_id) is not None, "CONTEXT-DELIVERY run_id is invalid")
    _require(bool(session_id), "CONTEXT-DELIVERY session_id is required")
    _require(re.fullmatch(r"[0-9a-f]{40}", base_sha) is not None, "CONTEXT-DELIVERY base_sha is invalid")
    _require(re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None, "CONTEXT-DELIVERY repository_fingerprint is invalid")
    if expected_run_id is not None:
        _require(run_id == expected_run_id, "CONTEXT-DELIVERY run_id differs from the active Council run")
    if expected_base_sha is not None:
        _require(base_sha == expected_base_sha, "CONTEXT-DELIVERY base_sha differs from the Council anchor")
    binding = plan.get("council_binding") or {}
    _require(binding.get("run_id") == run_id, "CONTEXT-DELIVERY run_id differs from CONTEXT-PLAN")
    _require(binding.get("base_sha") == base_sha, "CONTEXT-DELIVERY base_sha differs from CONTEXT-PLAN")
    _require(
        binding.get("repository_fingerprint") == fingerprint,
        "CONTEXT-DELIVERY repository fingerprint differs from CONTEXT-PLAN",
    )
    if verify_current_repository:
        _require(
            repository_fingerprint(repository_root) == fingerprint,
            "CONTEXT-DELIVERY repository fingerprint drifted after context collection",
        )
    lifecycle = _verify_lifecycle(repository_root, delivery, plan)
    tool_records, tools = _verify_tools(repository_root, delivery, lifecycle)
    resolutions = _verify_predicates(delivery, plan, tools)
    artifacts = _verify_artifacts(repository_root, delivery, plan, tools, resolutions)
    provider = _verify_provider(delivery, plan, tools, resolutions)
    _verify_coverage(delivery, plan, repository_root, tools)
    _verify_metrics(delivery, lifecycle, len(tools))
    claims = delivery.get("claims", [])
    _require(isinstance(claims, list) and claims, "CONTEXT-DELIVERY requires at least one evidence-bound claim")
    artifact_paths = {item["path"] for item in artifacts.values()}
    for number, claim in enumerate(claims, 1):
        _require(bool(claim.get("claim")), f"claim {number} is empty")
        evidence = claim.get("evidence")
        _require(isinstance(evidence, list) and evidence, f"claim {number} has no evidence")
        locator_ok = False
        for locator in evidence:
            locator_text = str(locator)
            if locator_text in artifact_paths:
                locator_ok = True
                break
            match = re.fullmatch(r"(.+):(\d+)", locator_text)
            if not match:
                continue
            candidate = (repository_root / match.group(1)).resolve()
            if repository_root.resolve() not in candidate.parents or not candidate.is_file():
                continue
            line_number = int(match.group(2))
            if line_number >= 1 and line_number <= len(candidate.read_text(encoding="utf-8", errors="replace").splitlines()):
                locator_ok = True
                break
        _require(locator_ok, f"claim {number} lacks an existing artifact or valid path:line locator")
    return {
        "plan_id": delivery["plan_id"],
        "run_id": run_id,
        "session_id": session_id,
        "base_sha": base_sha,
        "repository_fingerprint": fingerprint,
        "agent_id": delivery["agent_id"],
        "agent_type": delivery["agent_type"],
        "runtime": delivery["runtime"],
        "model": delivery["model"],
        "coverage": dict(delivery["coverage"]),
        "methods": sorted(artifacts),
        "tool_calls": len(tools),
        "predicate_resolutions": {key: value["status"] for key, value in resolutions.items()},
        "provider_state": provider,
        "execution_metrics": dict(delivery["execution_metrics"]),
    }
