#!/usr/bin/env python3
"""Compatibility entrypoint for the canonical Council contract validator."""
from __future__ import annotations
import runpy
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "engine" / "contract" / "scripts" / "validate_contract.py"
namespace = runpy.run_path(str(TARGET))
raise SystemExit(namespace["main"]())
