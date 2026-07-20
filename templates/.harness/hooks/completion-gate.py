#!/usr/bin/env python3
"""completion-gate — Stop hook (dual-runtime: Claude Code and Codex).

Blocks turn-end when the assistant's LAST message contains a plan-level completion
claim (100%, "plan executed", "all fixed", "all done", "task complete"...) without
the `prova-de-conclusao` skill's evidence block (full sentinel
`PROVA-DE-CONCLUSAO: x/y PASS, gaps: [...]`). Origin: friction audit 2026-07-03,
cluster 1 (42 overclaim incidents across 12 sessions).

Dual-runtime payload (confirmed via WebFetch learn.chatgpt.com/docs/hooks this
session — H3/A1-2): Claude Code sends `transcript_path` (JSONL) and does NOT send
`last_assistant_message`; Codex sends both fields, but `transcript_path` may be
`null` — `last_assistant_message` (string) is the only reliable turn-text source
in that runtime. So the `last_assistant_message` field, when present and non-empty,
takes PRIORITY over transcript parsing (Claude-specific, absent from the real Codex
payload); it only falls back to transcript parsing when that field is absent/empty
(the Claude path, unchanged).

Contract: exit 0 = allow stop; exit 2 = block (stderr goes to the model).
`stop_hook_active` true = already blocked once this turn → allow (avoids a loop).
Fail-open: any internal error allows the stop.
"""
import json
import re
import sys

# PLAN-level claims only — single-change claims ("file fixed") pass on purpose;
# for those the `verify` skill applies. PT and EN (H3/A1-2: the Codex payload may
# arrive in English; the regex used to cover only Portuguese).
CLAIM_RE = re.compile(
    r"""(?ix)(
        \b100\s*\%
      | \bplano\s+(?:foi\s+)?(?:executado|conclu[ií]do|finalizado)
      | \bexecutad[oa]s?\s+(?:integralmente|por\s+completo|na\s+[ií]ntegra)
      | \btudo\s+(?:foi\s+)?(?:implementad|corrigid|finalizad|conclu[ií]d)
      | \btodos?\s+os\s+(?:itens|gaps|p0s?|pontos|cr[ií]ticos)\s+(?:foram\s+)?
            (?:fechad|resolvid|corrigid|implementad|conclu[ií]d)
      | \bpronto\s+para\s+(?:produ[çc][ãa]o|homolog|deploy|entrega)
      | \bgaps?\s+zerad
      | \bimplementa[çc][ãa]o\s+(?:est[áa]\s+)?completa
      | \bplan\s+is\s+(?:complete|executed|finished|done)
      | \ball\s+(?:done|fixed|complete[d]?|resolved|finished|implemented)
      | \beverything\s+(?:is\s+|has\s+been\s+)?(?:done|fixed|complete[d]?|resolved|implemented)
      | \btask\s+(?:is\s+)?complete[d]?
      | \bfully\s+(?:implemented|fixed|resolved|complete)
      | \bready\s+for\s+(?:production|deploy(?:ment)?|release)
      | \b(?:all\s+)?gaps?\s+(?:are\s+)?(?:zero|none|closed)
      | \bimplementation\s+is\s+complete
    )"""
)
# The sentinel REQUIRES the full format (raw "x/y" is not enough): number/number,
# literal PASS, comma, literal gaps: — H3/A1-2, real finding: the previous regex
# accepted any "0/999" as if it were the evidence block.
SENTINEL_RE = re.compile(
    r"PROVA-DE-CONCLUSAO:\s*\d+\s*/\s*\d+\s*PASS\s*,\s*gaps\s*:", re.IGNORECASE
)
TAIL_BYTES = 2_000_000  # transcripts reach 45MB; only the tail matters


def assistant_texts_from_tail(path):
    """Latest assistant texts (main loop, no sidechains), most recent last."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    texts = []
    for line in raw.splitlines():
        if '"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue  # the first line of the tail may be truncated
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        txt = " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if txt:
            texts.append(txt)
    return texts


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0  # already blocked once this turn

    last_assistant_message = data.get("last_assistant_message")
    if isinstance(last_assistant_message, str) and last_assistant_message.strip():
        # Codex: the payload already carries the turn's final text; transcript_path
        # may be null and, even when present, is not the JSONL format that
        # assistant_texts_from_tail knows how to parse (that is Claude-specific).
        texts = [last_assistant_message]
    else:
        transcript = data.get("transcript_path")
        if not transcript:
            return 0
        texts = assistant_texts_from_tail(transcript)
        if not texts:
            return 0
    last = texts[-1]
    if not CLAIM_RE.search(last):
        return 0
    # the sentinel may be in this message or just before it (verdict in a prior msg)
    if any(SENTINEL_RE.search(t) for t in texts[-3:]):
        return 0
    sys.stderr.write(
        "COMPLETION-GATE: plan-level completion claim without an evidence block.\n"
        "Before declaring 100%/plan executed/all fixed, run the `prova-de-conclusao` "
        "skill: for each declared item, THIS-SESSION evidence (command + exit code, "
        "grep with path+line, test counts, ui-evidence manifest, curl on the prod "
        "URL) in a table, ending with the literal line "
        "`PROVA-DE-CONCLUSAO: <x>/<y> PASS, gaps: [ids or 'none']`.\n"
        "If there is no evidence for an item, it's a gap — reword the verdict without "
        "the completion claim instead of fabricating certainty.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
