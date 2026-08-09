#!/usr/bin/env python3
"""Pure decisions used by Council PreToolUse, PostToolUse, Stop and Git guards."""

from __future__ import annotations

from typing import Any

from council_runtime import remote_action_allowed


def pre_tool_guard(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("tool_name") not in {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}:
        return {"allow": True}
    stage = payload.get("state", {}).get("stage")
    allowed = stage in {"ITEM-PLAN", "SLICE"}
    return {"allow": allowed, "reason": None if allowed else "Edit/Write requires ITEM-PLAN: PRONTO"}


def post_tool_guard(payload: dict[str, Any]) -> dict[str, Any]:
    edited = payload.get("tool_name") in {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"} and payload.get("success", True)
    return {"allow": True, "required_next": "VALIDATION" if edited else None}


def stop_guard(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state", {})
    delivered = state.get("stage") == "DELIVERY" and state.get("delivery_verified") is True and any(item.get("event") == "DELIVERY" for item in state.get("history", []))
    return {"allow": delivered, "reason": None if delivered else "Council completion requires DELIVERY evidence"}


def git_guard(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", ""))
    allowed = remote_action_allowed(action, payload.get("authority", {}))
    return {"allow": allowed, "reason": None if allowed else "remote push/merge-main requires explicit authorization evidence"}
