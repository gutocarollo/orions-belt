"""Safe, non-executing corpus ingestion primitives."""

from .pipeline import build_manifest, curate, promote, summarize_validation, validate_manifest

__all__ = ["build_manifest", "curate", "promote", "summarize_validation", "validate_manifest"]
