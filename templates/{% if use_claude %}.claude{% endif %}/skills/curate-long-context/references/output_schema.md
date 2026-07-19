# Output Schema

The canonical artifact is newline-delimited JSON. Each line is one JSON object. Sort records by the first source line in `source_ranges`.

## Required Fields

- `id`: Stable string, such as `E1` or `chunk-0007`.
- `kind`: One of `episode`, `chunk_curation`, `global_summary`, `decision_log`, or `open_items`.
- `title`: Short human-readable title.
- `source_file`: Path to the source transcript used for validation.
- `source_sha256`: SHA-256 hash emitted by `prepare_context.py`.
- `source_ranges`: List of inclusive source line ranges. Use objects with `start` and `end`.
- `summary`: Dense factual summary of what happened in the record.
- `user_requests`: List of user requests, corrections, constraints, or acceptance criteria.
- `assistant_conclusions`: List of assistant conclusions, verdicts, claims, and stated confidence limits.
- `files_analyzed`: List of files, paths, URLs, commits, branches, databases, services, or artifacts analyzed.
- `commands_or_tools`: List of commands, tools, MCPs, scripts, tests, browser/web actions, or runtime checks used.
- `decisions`: List of decisions made, recommendations, rejected options, or chosen next steps.
- `risks_or_open_questions`: List of risks, blockers, unresolved questions, caveats, or follow-up checks.
- `evidence_quotes`: List of quote objects. Each object must contain `quote`, `source_range`, and optional `note`.

## Anti-loss conventions (enforced by SKILL.md rules + values-ledger validation)

- **Literal values are copied, never categorized**: env names, versions, hashes, ports, durations, estimates, counts, ratios, exact file/function names. The validator cross-checks the chunk `values_ledger`; anything not copied must be listed in `dropped_values`.
- **Attribution**: decisions record who decided — `"(usuario, cru)"`, `"(adaptacao do assistente porque X)"`, `"(recomendacao delegada)"`.
- **Negations verbatim**: never soften "CANNOT"/"NEVER"/"WRONG" into weaker phrasing.
- **Source corrections**: when the transcript proves a comment/doc is wrong, record error + verified truth as one fact.
- **Language**: summaries/requests/conclusions/decisions in the user's language; quotes verbatim in the source language.

## Evidence Quote Format

```json
{
  "quote": "short exact or whitespace-normalized excerpt from the source",
  "source_range": {"start": 120, "end": 130},
  "note": "why this quote supports the record"
}
```

Rules:

- Keep quotes short and source-backed.
- Quote only text that appears inside the declared `source_range`.
- Use multiple small quotes rather than long copied passages.
- Do not use a quote as decoration; each quote should support a claim that matters.

## Example Record

```json
{
  "id": "E1",
  "kind": "episode",
  "title": "HR Chat QA gaps",
  "source_file": "CONTEXT-ANYTHING.TXT",
  "source_sha256": "replace-with-manifest-hash",
  "source_ranges": [{"start": 1, "end": 926}],
  "summary": "The conversation identified and fixed HR Chat QA gaps around Q29 and Q30, then validated the behavior with targeted tests and a full suite.",
  "user_requests": [
    "Audit whether the HR Chat QA gaps were fully addressed.",
    "Preserve concrete files, tests, and runtime evidence."
  ],
  "assistant_conclusions": [
    "Q29 and Q30 required explicit handling rather than a generic summary.",
    "The fix was considered validated only after focused and broad tests passed."
  ],
  "files_analyzed": [
    "backend/app/services/hr_bi_service.py",
    "backend/tests/unit/test_bi_gaps.py"
  ],
  "commands_or_tools": [
    "pytest backend/tests/unit/test_bi_gaps.py"
  ],
  "decisions": [
    "Treat line-ranged evidence as mandatory for the compacted artifact."
  ],
  "risks_or_open_questions": [
    "Rendered Markdown is not canonical; JSONL remains the source of truth."
  ],
  "evidence_quotes": [
    {
      "quote": "Q29",
      "source_range": {"start": 1, "end": 926},
      "note": "Identifies one of the concrete QA gaps discussed."
    }
  ]
}
```

## Optional Fields

Optional fields are allowed, but keep them stable and useful:

- `confidence`: `high`, `medium`, or `low`.
- `curator_notes`: Notes about interpretation choices or skipped details.
- `related_records`: List of related record IDs.
- `canonical_tags`: Stable tags such as `qa`, `architecture`, `migration`, `risk`, `decision`.
- `gotchas`: List of operational traps a future session must know BEFORE acting (invalid shell env vars, restart procedures, auth headers for probes, per-worker state, gating preconditions, stale/wrong comments in code). These feed the `--digest` render's "Gotchas" section — write them as imperative one-liners.
- `dropped_values`: List of literal values from the chunk `values_ledger` deliberately NOT copied into the record (decorative numbers, redundant restatements). Presence here tells the validator the omission was a decision, not a loss.

Avoid ad hoc fields when an existing required field can express the information.
