#!/usr/bin/env python3
"""Structured fields derived from full, untruncated runtime tool output."""
from __future__ import annotations

import json
import re
from typing import Any

DEFINITION_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.[A-Za-z0-9_+-]+:\d+)(?!\d)"
)


def definition_ids(value: Any) -> list[str]:
    """Extract every unique path:line identity before observability truncation."""
    if value is None:
        return []
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str
    )
    return sorted(set(DEFINITION_ID_RE.findall(text)))
