#!/usr/bin/env python3
"""Conservative parser for provider status receipts.

Freshness is never accepted because a worker wrote `index_fresh=true`. The
receipt must be linked to a successful runtime tool call and contain explicit
provider output proving zero pending/stale changes.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any


class ProviderProbeError(ValueError):
    pass


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"true", "yes", "fresh", "up-to-date", "up to date"}:
            return True
        if value.lower() in {"false", "no", "stale"}:
            return False
    return None


def _unwrap(value: Any) -> Any:
    # Hook outputs may be JSON-encoded strings or MCP content wrappers.
    for _ in range(3):
        if isinstance(value, str):
            text = value.strip()
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return value
            if decoded == value:
                return value
            value = decoded
            continue
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            texts = [item.get("text") for item in value["content"] if isinstance(item, dict) and isinstance(item.get("text"), str)]
            if texts:
                value = "\n".join(texts)
                continue
        if isinstance(value, dict) and "result" in value and len(value) <= 4:
            value = value["result"]
            continue
        if isinstance(value, dict):
            for key in ("stdout", "output", "text"):
                if isinstance(value.get(key), str) and value[key].strip():
                    value = value[key]
                    break
            else:
                break
            continue
        break
    return value


def parse_codegraph_status(value: Any) -> dict[str, Any]:
    value = _unwrap(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if value is None:
            pending_match = re.search(r"(?i)pending(?:\s+changes?|\s+files?|\s+sync)?\s*[:=]\s*(\d+)", text)
            pending_none = bool(re.search(r"(?i)pending(?:\s+changes?|\s+files?|\s+sync)?\s*[:=]\s*(none|clean|no|zero)\b", text))
            stale_false = bool(re.search(r"(?i)\bstale\s*[:=]\s*(false|no|0)\b", text))
            explicit_fresh = bool(
                re.search(
                    r"(?i)\b(?:code\s*graph|graph|index|database)"
                    r"(?:\s+status)?\s*(?::|=)?\s*(?:is\s+)?"
                    r"(?:fresh|up[- ]to[- ]date|synchroni[sz]ed|current)\b",
                    text,
                )
                or re.search(
                    r"(?i)\b(?:fresh|up[- ]to[- ]date|synchroni[sz]ed|current)"
                    r"\s+(?:code\s*graph|graph|index|database)\b",
                    text,
                )
            )
            pending = int(pending_match.group(1)) if pending_match else (0 if pending_none or explicit_fresh or stale_false else None)
            if pending is None or not (stale_false or explicit_fresh or pending_none):
                raise ProviderProbeError("CodeGraph text did not explicitly prove freshness and pending=0")
            return {
                "provider": "codegraph",
                "status": "AVAILABLE",
                "index_fresh": pending == 0,
                "pending_changes": pending,
                "provider_version": "UNKNOWN",
                "indexed_sha": None,
                "head_sha": None,
            }
    if not isinstance(value, dict):
        raise ProviderProbeError("CodeGraph status must be an object or explicit status text")
    pending = value.get("pending_changes", value.get("pendingChanges", value.get("pending", value.get("dirty_files"))))
    if isinstance(pending, list):
        pending = len(pending)
    if isinstance(pending, dict):
        counts: list[int] = []
        for name, item in pending.items():
            if isinstance(item, list):
                counts.append(len(item))
            elif isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                counts.append(item)
            else:
                raise ProviderProbeError(f"CodeGraph pendingChanges.{name} is not a non-negative count or list")
        pending = sum(counts)
    if not isinstance(pending, int):
        raise ProviderProbeError("CodeGraph status lacks an integer pending_changes field")
    fresh = _bool(value.get("index_fresh", value.get("indexFresh", value.get("fresh"))))
    stale = _bool(value.get("stale"))
    if fresh is None and stale is not None:
        fresh = not stale
    indexed_sha = value.get("indexed_sha", value.get("indexedSha", value.get("git_sha", value.get("gitSha"))))
    head_sha = value.get("head_sha", value.get("headSha", value.get("repository_sha")))
    if fresh is None and indexed_sha and head_sha:
        fresh = str(indexed_sha) == str(head_sha) and pending == 0
    index = value.get("index")
    if fresh is None and isinstance(index, dict):
        state = str(index.get("state") or "").lower()
        pending_refs = index.get("pendingRefs", index.get("pending_refs"))
        reindex = index.get("reindexRecommended", index.get("reindex_recommended"))
        worktree_mismatch = value.get("worktreeMismatch", value.get("worktree_mismatch"))
        built_extraction = index.get("builtWithExtractionVersion")
        current_extraction = index.get("currentExtractionVersion")
        extraction_current = (
            built_extraction is None
            or current_extraction is None
            or built_extraction == current_extraction
        )
        fresh = bool(
            state == "complete"
            and pending_refs == 0
            and reindex is False
            and worktree_mismatch in {None, False}
            and extraction_current
            and pending == 0
        )
    if fresh is None:
        raise ProviderProbeError("CodeGraph status lacks explicit freshness evidence")
    return {
        "provider": "codegraph",
        "status": "AVAILABLE",
        "index_fresh": bool(fresh and pending == 0),
        "pending_changes": pending,
        "provider_version": str(value.get("version", value.get("provider_version", "UNKNOWN"))),
        "indexed_sha": str(indexed_sha) if indexed_sha else None,
        "head_sha": str(head_sha) if head_sha else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("codegraph",))
    parser.add_argument("--input-json", required=True)
    args = parser.parse_args()
    raw: Any = args.input_json
    try:
        raw = json.loads(raw)
    except json.JSONDecodeError:
        pass
    print(json.dumps(parse_codegraph_status(raw), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
