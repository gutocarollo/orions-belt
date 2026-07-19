#!/usr/bin/env python3
"""Prepare a long transcript for traceable curation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable


MARKER_PATTERNS = [
    ("markdown_heading", re.compile(r"^\s{0,3}#{1,6}\s+\S")),
    ("speaker_label", re.compile(r"^\s*(user|assistant|system|developer|tool|function)\b\s*[:：]", re.I)),
    ("xmlish_speaker", re.compile(r"^\s*</?(user|assistant|system|developer|tool|function)\b", re.I)),
    ("tool_call", re.compile(r"\b(tool_use|tool_result|exec_command|apply_patch|web\.run|mcp__)\b", re.I)),
    ("separator", re.compile(r"^\s*[-=_*]{3,}\s*$")),
]

FILE_REF_RE = re.compile(
    r"(?<![\w@])(?:[A-Za-z]:)?(?:~?/|\.{1,2}/|[A-Za-z0-9_.-]+/)[A-Za-z0-9_./@+~:=-]*"
    r"\.(?:py|ts|tsx|js|jsx|mjs|cjs|md|txt|json|jsonl|ya?ml|toml|ini|env|sql|sh|bash|zsh|css|scss|html|csv|log|lock|prisma|tsx?)"
)

COMMAND_HINT_RE = re.compile(
    r"^\s*(?:python3?|pytest|npm|pnpm|yarn|npx|uv|ruff|mypy|tsc|node|git|rg|sed|awk|cat|ls|find|docker|docker-compose|curl|gh)\b"
)

# Literal-value candidates: tokens that must never be silently genericized by the
# curator. Each pattern targets one class of operational literal.
VALUE_PATTERNS = [
    ("env_or_flag", re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,}\b")),
    ("cli_flag", re.compile(r"(?<!\w)--[a-z][a-z0-9-]{2,}\b")),
    ("version", re.compile(r"\bv?\d+\.\d+(?:\.\d+)+\b|\bv\d+\.\d+\b")),
    ("hash", re.compile(r"\b[0-9a-f]{8,64}\b")),
    ("ratio_or_score", re.compile(r"\b\d+/\d+\b")),
    ("duration_or_size", re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|s|min|mins|minutos|h|d|dias|semanas|MB|GB|KB|TB|%)\b")),
    ("port_or_code", re.compile(r"(?<=:)\d{2,5}\b|\bHTTP\s?\d{3}\b|\b(?:status|exit|code)\s\d{3}\b")),
    ("counted_noun", re.compile(r"\b\d{1,6}\s(?:passed|failed|errors?|warnings?|linhas?|lines?|rows?|threads?|tests?|casos?|files?|arquivos?|tools?|keys?|users?|usu[aá]rios?)\b", re.I)),
]

VALUE_STOPWORDS = {
    "TODO", "NOTE", "WARNING", "ERROR", "INFO", "DEBUG", "TRUE", "FALSE", "NULL",
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "SELECT", "FROM",
    "WHERE", "JOIN", "AND", "NOT", "THE", "OUT", "README", "LICENSE",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_char_count(lines: list[str], start: int, end: int) -> int:
    return sum(len(line) for line in lines[start - 1 : end])


def marker_kind(line: str) -> str | None:
    for name, pattern in MARKER_PATTERNS:
        if pattern.search(line):
            return name
    return None


def paragraph_segments(lines: list[str]) -> list[tuple[int, int]]:
    """Return inclusive line ranges grouped by blank lines and hard markers."""
    segments: list[tuple[int, int]] = []
    start: int | None = None
    prev = 0

    for idx, line in enumerate(lines, start=1):
        is_blank = not line.strip()
        is_marker = marker_kind(line) is not None

        if start is None:
            if is_blank:
                segments.append((idx, idx))
            else:
                start = idx
            prev = idx
            continue

        if is_marker and idx > start:
            segments.append((start, prev))
            start = idx
        elif is_blank:
            segments.append((start, idx))
            start = None

        prev = idx

    if start is not None:
        segments.append((start, len(lines)))
    return segments


def split_large_segment(
    lines: list[str],
    start: int,
    end: int,
    max_chars: int,
    max_lines: int,
) -> Iterable[tuple[int, int]]:
    chunk_start = start
    chars = 0
    count = 0
    for line_no in range(start, end + 1):
        line_len = len(lines[line_no - 1])
        if count and (chars + line_len > max_chars or count + 1 > max_lines):
            yield (chunk_start, line_no - 1)
            chunk_start = line_no
            chars = 0
            count = 0
        chars += line_len
        count += 1
    if chunk_start <= end:
        yield (chunk_start, end)


def build_chunks(
    lines: list[str],
    max_chars: int,
    max_lines: int,
) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None
    current_chars = 0
    current_lines = 0

    def flush() -> None:
        nonlocal current_start, current_end, current_chars, current_lines
        if current_start is not None and current_end is not None:
            chunks.append((current_start, current_end))
        current_start = None
        current_end = None
        current_chars = 0
        current_lines = 0

    for seg_start, seg_end in paragraph_segments(lines):
        seg_chars = line_char_count(lines, seg_start, seg_end)
        seg_lines = seg_end - seg_start + 1

        if seg_chars > max_chars or seg_lines > max_lines:
            flush()
            chunks.extend(split_large_segment(lines, seg_start, seg_end, max_chars, max_lines))
            continue

        would_exceed = (
            current_start is not None
            and (current_chars + seg_chars > max_chars or current_lines + seg_lines > max_lines)
        )
        if would_exceed:
            flush()

        if current_start is None:
            current_start = seg_start
        current_end = seg_end
        current_chars += seg_chars
        current_lines += seg_lines

    flush()
    return chunks


def first_nonblank(lines: list[str], start: int, end: int) -> str:
    for line in lines[start - 1 : end]:
        stripped = line.strip()
        if stripped:
            return stripped[:180]
    return ""


def write_chunk(path: Path, source_path: Path, source_hash: str, lines: list[str], start: int, end: int) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# chunk_id: {path.stem}\n")
        fh.write(f"# source: {source_path}\n")
        fh.write(f"# source_sha256: {source_hash}\n")
        fh.write(f"# line_range: {start}-{end}\n")
        fh.write("# format: original_line_number | source_text\n\n")
        for line_no in range(start, end + 1):
            fh.write(f"{line_no:06d} | {lines[line_no - 1]}")
            if not lines[line_no - 1].endswith("\n"):
                fh.write("\n")


def collect_markers(lines: list[str]) -> dict[str, list[int]]:
    markers: dict[str, list[int]] = {name: [] for name, _ in MARKER_PATTERNS}
    for idx, line in enumerate(lines, start=1):
        for name, pattern in MARKER_PATTERNS:
            if pattern.search(line):
                markers[name].append(idx)
    return {name: values for name, values in markers.items() if values}


def collect_file_refs(lines: list[str], limit: int) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    first_line: dict[str, int] = {}
    for line_no, line in enumerate(lines, start=1):
        for match in FILE_REF_RE.findall(line):
            counts[match] += 1
            first_line.setdefault(match, line_no)
    return [
        {"path": path, "count": count, "first_line": first_line[path]}
        for path, count in counts.most_common(limit)
    ]


def collect_command_hints(lines: list[str], limit: int) -> list[dict[str, object]]:
    hints = []
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if COMMAND_HINT_RE.search(stripped):
            hints.append({"line": line_no, "command": stripped[:240]})
        if len(hints) >= limit:
            break
    return hints


def collect_value_candidates(lines: list[str], start: int, end: int, limit: int = 120) -> list[dict[str, object]]:
    """Deterministically inventory literal-value candidates inside a line range.

    These are the tokens a curator must copy verbatim or explicitly list in
    `dropped_values` — the anti-genericization ledger.
    """
    seen: set[str] = set()
    values: list[dict[str, object]] = []
    for line_no in range(start, min(end, len(lines)) + 1):
        line = lines[line_no - 1]
        for kind, pattern in VALUE_PATTERNS:
            for match in pattern.findall(line):
                token = match if isinstance(match, str) else match[0]
                token = token.strip()
                if not token or token.upper() in VALUE_STOPWORDS:
                    continue
                if kind == "env_or_flag" and len(token) < 5:
                    continue
                key = f"{kind}:{token}"
                if key in seen:
                    continue
                seen.add(key)
                values.append({"kind": kind, "value": token, "line": line_no})
                if len(values) >= limit:
                    return values
    return values


def make_template_record(source_path: Path, source_hash: str, chunk_id: str, start: int, end: int) -> dict[str, object]:
    return {
        "id": chunk_id,
        "kind": "chunk_curation",
        "title": "",
        "source_file": str(source_path),
        "source_sha256": source_hash,
        "source_ranges": [{"start": start, "end": end}],
        "summary": "",
        "user_requests": [],
        "assistant_conclusions": [],
        "files_analyzed": [],
        "commands_or_tools": [],
        "decisions": [],
        "risks_or_open_questions": [],
        "gotchas": [],
        "evidence_quotes": [],
        "dropped_values": [],
        "confidence": "medium",
        "canonical_tags": [],
        "curator_notes": "TODO: fill from the matching chunk before validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Transcript/context file to prepare")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--max-chars", type=int, default=12_000, help="Maximum characters per chunk")
    parser.add_argument("--max-lines", type=int, default=350, help="Maximum source lines per chunk")
    parser.add_argument("--top-file-refs", type=int, default=200, help="Number of file references to include")
    parser.add_argument("--command-hints", type=int, default=200, help="Number of command-like lines to include")
    args = parser.parse_args()

    source_path = args.source.expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"source file not found: {source_path}")
    if args.max_chars < 1000:
        raise SystemExit("--max-chars must be at least 1000")
    if args.max_lines < 20:
        raise SystemExit("--max-lines must be at least 20")

    data = source_path.read_bytes()
    source_hash = sha256_bytes(data)
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    out_dir = args.out.expanduser().resolve()
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunks = build_chunks(lines, args.max_chars, args.max_lines)
    chunk_records = []
    for index, (start, end) in enumerate(chunks, start=1):
        chunk_id = f"chunk-{index:04d}"
        chunk_path = chunks_dir / f"{chunk_id}.txt"
        write_chunk(chunk_path, source_path, source_hash, lines, start, end)
        chunk_records.append(
            {
                "id": chunk_id,
                "path": str(chunk_path),
                "start_line": start,
                "end_line": end,
                "line_count": end - start + 1,
                "char_count": line_char_count(lines, start, end),
                "first_nonblank": first_nonblank(lines, start, end),
                "values_ledger": collect_value_candidates(lines, start, end),
            }
        )

    markers = collect_markers(lines)
    manifest = {
        "source_file": str(source_path),
        "source_sha256": source_hash,
        "line_count": len(lines),
        "char_count": len(text),
        "byte_count": len(data),
        "replacement_char_count": text.count("\ufffd"),
        "parameters": {
            "max_chars": args.max_chars,
            "max_lines": args.max_lines,
        },
        "marker_counts": {name: len(values) for name, values in markers.items()},
        "markers": markers,
        "top_file_refs": collect_file_refs(lines, args.top_file_refs),
        "command_hints": collect_command_hints(lines, args.command_hints),
    }

    chunks_manifest = {
        "source_file": str(source_path),
        "source_sha256": source_hash,
        "chunk_count": len(chunk_records),
        "chunks": chunk_records,
        "oversize_chunks": [
            record
            for record in chunk_records
            if record["char_count"] > args.max_chars or record["line_count"] > args.max_lines
        ],
    }

    (out_dir / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "chunks_manifest.json").write_text(
        json.dumps(chunks_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with (out_dir / "curated.template.jsonl").open("w", encoding="utf-8") as fh:
        for record in chunk_records:
            template = make_template_record(
                source_path,
                source_hash,
                str(record["id"]),
                int(record["start_line"]),
                int(record["end_line"]),
            )
            fh.write(json.dumps(template, ensure_ascii=False, sort_keys=True) + "\n")

    print(
        json.dumps(
            {
                "source_file": str(source_path),
                "source_sha256": source_hash,
                "line_count": len(lines),
                "char_count": len(text),
                "chunk_count": len(chunk_records),
                "out_dir": str(out_dir),
                "oversize_chunk_count": len(chunks_manifest["oversize_chunks"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
