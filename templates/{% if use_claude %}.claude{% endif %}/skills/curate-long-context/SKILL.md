---
name: curate-long-context
description: Curate and compact long chat transcripts, CONTEXT.TXT files, Codex/Claude context dumps, JSONL chat logs, and pre-compact handoff material into traceable structured artifacts. Use when a user asks to preserve, audit, summarize, compact, or turn a long conversation into reusable context while retaining user requests, assistant conclusions, files analyzed, commands/tools, decisions, risks, open questions, source line ranges, and verifiable evidence quotes.
---

# Curate Long Context

## Purpose

Turn long conversations into durable context without flattening them into a vague summary. Deterministic scripts handle inspection, splitting, values inventory, validation, and rendering; the model does only the semantic curation inside a fixed schema, under anti-loss rules.

## Core law (inherited from the context-to-html method)

**Compression happens only by ELIMINATION of irrelevant material, never by AGGREGATION of relevant facts.** The dominant failure mode of every naive compressor is silent loss of concrete instances under categorical abstraction: "envs configured" instead of the seven env names, "dangerous skills off" instead of the four skill names, "the plan has estimates" instead of `20-31 days, F3 critical 5-8d`. A relevant fact survives verbatim — or with equivalent specificity — or it is explicitly listed as dropped. There is no third option called "summarized for brevity".

## The nine anti-loss rules (apply during curation, checked at the gates)

1. **Literal values never become categories.** Numbers, versions, hashes, env names, flags, ports, durations, estimates, counts, ratios (`46/46`, `30/30`), exact file/function names: copy them. The `values_ledger` in `chunks_manifest.json` is the deterministic inventory — every ledger value inside your record's ranges must appear in the record or in its `dropped_values` list.
2. **Negations are never softened.** "CANNOT be re-displayed" must not become "no robust re-display"; "NEVER emitted" must not become "rarely used"; "the comment is WRONG/STALE" must not become "possibly outdated".
3. **Decision attribution is preserved.** Distinguish (a) the user's raw choice, (b) an adaptation made by the assistant, (c) an assistant recommendation the user delegated. "User chose A; assistant adapted to A-modified because X" is one fact — do not collapse it to "decision: A-modified".
4. **Source-correction facts are first-class.** When the transcript proves something in the code/docs/upstream is wrong (a stale comment, an incorrect upstream docstring), record both the error and the verified truth. These are the facts most likely to burn a future session.
5. **Failed attempts and discarded routes survive.** A first commit that failed, a follow-up evaluated and deliberately rejected, an interrupted workflow — record them so future sessions do not rediscover or redo them.
6. **Operational gotchas are extracted aggressively**: invalid env vars in the shell, which process to restart and how, auth headers needed for probes, per-worker vs shared state, ordering/gating preconditions ("X only after Y exists"). Put them in the `gotchas` field — they feed the digest.
7. **User pain and framing survive as user requests**, not just as technical findings later. The motivating pain is an acceptance criterion.
8. **Language follows the user/source.** Curate summaries, requests, conclusions, decisions in the user's language; evidence quotes stay verbatim in the source language.
9. **No silent sampling.** If a list has N items in the source and only K matter, name the K and say what class was dropped and why (in `curator_notes` or `dropped_values`).

## Contract

Do not claim the output was produced by this skill unless all required gates ran:

1. Run `prepare_context.py` against the source transcript (produces manifests, chunks, values ledger).
2. Create or update the curated JSONL using `references/output_schema.md`.
3. Run `validate_curated_jsonl.py` with `--require-evidence` AND `--values-ledger <out>/chunks_manifest.json`. Fix all errors; treat every values-ledger warning as a decision to make (copy the value or declare it dropped), never as noise.
4. Run the **adversarial recall audit** (see Gate R below) for high-stakes curation, or explicitly disclose it was skipped.
5. Render BOTH artifacts with `render_curated_markdown.py`: the full document and the `--digest` rehydration digest (or state why one was skipped).
6. Leave a pointer where the next session will find it (see "Anchoring the artifact").

Determinism: scripts produce identical manifests/chunks/renders for the same input and parameters. The semantic curation is stable in facts and structure, but byte-identical only when the same curated JSONL is reused as golden.

Do not use external APIs, API keys, embeddings, vector stores, or background services unless the user explicitly asks. Default mode is local scripts plus the current session.

## Gate R — adversarial recall audit (the gate that catches what self-review cannot)

Self-review converges to self-approval: whoever compressed also decides what "complete" means. For any curation the user will rely on (or when asked "is this complete?"):

1. Partition the source by episode boundaries.
2. For each segment, run an INDEPENDENT reviewer (a subagent when the harness has them; otherwise a separate pass reading ONLY the raw segment plus the curated artifact — never your curation notes).
3. Each reviewer inventories the segment's relevant facts and reports only what is MISSING or DISTORTED in the artifact, with severity: CRITICAL (a future session would act wrongly without it), USEFUL (recoverable elsewhere but costly), NOISE.
4. Patch every CRITICAL and USEFUL finding into the JSONL, re-validate, re-render.
5. Report the recall scorecard (facts inventoried, losses by severity) in the final answer.

The reviewers verify against the SOURCE, not against your criteria — criteria written after curation are self-validating and worthless as a gate.

## Quick Start

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"  # or the absolute skill path

python3 "$SKILL_DIR/scripts/prepare_context.py" CONTEXT.TXT --out .curate/context

# Curate: copy curated.template.jsonl -> curated.jsonl and fill each record
# from the matching .curate/context/chunks/chunk-*.txt, applying the nine rules.

python3 "$SKILL_DIR/scripts/validate_curated_jsonl.py" \
  --source CONTEXT.TXT .curate/context/curated.jsonl \
  --require-evidence --values-ledger .curate/context/chunks_manifest.json

python3 "$SKILL_DIR/scripts/render_curated_markdown.py" \
  .curate/context/curated.jsonl --source CONTEXT.TXT --out CONTEXT.CURATED.md
python3 "$SKILL_DIR/scripts/render_curated_markdown.py" \
  .curate/context/curated.jsonl --source CONTEXT.TXT --digest --out CONTEXT.DIGEST.md
```

## Workflow

### 1. Inspect and split

Run `prepare_context.py` (`--max-chars 12000` default for ~100k-token transcripts). Review `source_manifest.json` (lines, hash, markers, file refs), `chunks_manifest.json` (chunk ranges, oversize warnings, **values_ledger per chunk**), and the line-numbered `chunks/chunk-*.txt`.

### 2. Curate into JSONL

Read `references/output_schema.md` first. For each chunk/episode extract only source-backed material: user requests and corrections (with the motivating pain); assistant conclusions and verdicts; files/paths/commits/branches/DBs/services analyzed; commands/tools/tests and their decisive outputs; decisions (with attribution) and rejected alternatives; risks, blockers, open questions; **gotchas**; evidence quotes with line ranges. Apply the nine rules. Prefer fewer high-signal records; sort by first source line. Consider one final `open_items`/`global_summary` record for cross-episode pendências.

### 3. Validate

`validate_curated_jsonl.py` after every JSONL change, with `--require-evidence` and `--values-ledger`. Every unaccounted ledger value is a forced decision: copy it into the record or add it to `dropped_values` with intent. Use `--strict-values` for final deliverables on dense technical transcripts.

### 4. Recall audit (Gate R)

Run for high-stakes curation. Patch findings, re-validate, re-render.

### 5. Render

Full document + `--digest`. The JSONL is canonical; Markdown is delivery. Never hand-edit renders except cosmetically.

### 6. Anchoring the artifact (do not orphan the output)

An artifact no future session loads solves nothing. After rendering:

- **Claude Code**: add a one-line pointer in the project memory index (`MEMORY.md`) linking the digest, e.g. `- Curadoria X → ../path/CONTEXT.DIGEST.md — <one-line hook>` (illustrative pointer format, not a literal markdown link — the real target path is whatever the digest actually rendered to).
- **Codex**: emit the artifact paths in the final answer and, if the user asked for persistence, write a note via the memory mechanism available.
- **Pre-compact use**: capture must be cheap and deterministic (save transcript + metadata + queue entry); NEVER run the full LLM curation inside a synchronous hook — curation runs manually or in background afterwards.

## Final answer to the user (minimum)

Name source and artifacts; validation result (including values-ledger accounting); recall-audit scorecard or the disclosure it was skipped; determinism statement; where the pointer was anchored.

## Resources

- `scripts/prepare_context.py`: inspection, marker/values inventory, chunking, JSONL template.
- `scripts/validate_curated_jsonl.py`: schema, ranges, hash, `quote ∈ source_range`, values-ledger coverage.
- `scripts/render_curated_markdown.py`: full render + `--digest` rehydration digest.
- `references/output_schema.md`: canonical JSONL schema (incl. `gotchas`, `dropped_values`).
- `references/quality_gates.md`: inclusion rules, anti-loss checklist, recall audit protocol, determinism.
