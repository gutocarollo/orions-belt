# Quality Gates

Use these gates before calling a curation complete.

## Inclusion Rules

Preserve:

- every explicit user request, correction, constraint, and "do not do X" instruction;
- conclusions from assistant, subagents, audits, external docs, and runtime checks;
- files and artifacts analyzed, including paths, commits, branches, schemas, tests, docs, URLs, and generated reports;
- commands/tools/tests and whether they passed, failed, timed out, or were not run;
- decisions, alternatives rejected, root causes, risks, blockers, and next steps;
- confidence limits and places where the source does not prove the claim.

Compress:

- repeated agreement language;
- progress chatter without new facts;
- long command output once the decisive lines are captured;
- duplicate file listings once the complete set is preserved elsewhere.

Do not invent:

- tests that were not run;
- files that were not inspected;
- certainty stronger than the source;
- a guarantee of byte-identical reruns unless a golden JSONL is reused.

## Total Coverage Mandate (anti-genericization)

The empirically dominant loss pattern is not omission of topics — it is **silent genericization**: the topic survives as a category while its literal values die ("envs configured", "extras", "dangerous skills off"). Locks:

- Every enumerated list in the source with N items: the record names all N, or names K and lists the rest in `dropped_values`/`curator_notes` with a reason.
- Every quantitative fact (estimates per phase, counts, ratios like `46/46`, limits, TTLs): the number itself appears, not a paraphrase.
- Every named thing a future session must type (env var, flag, endpoint, table, function, workspace name): verbatim.
- The values-ledger check in the validator is the mechanical floor for this — but it cannot see multi-word names or SQL fragments, so the curator still applies the rule beyond what the ledger catches.

## Adversarial Checks

Before finalizing, ask:

- Does every major conclusion have a source range or evidence quote?
- Are user corrections preserved as first-class facts, not hidden in prose?
- Are tool outputs and failed attempts included when they changed the decision?
- Is decision attribution preserved (user raw choice vs assistant adaptation vs delegated recommendation)?
- Are negations verbatim (no "CANNOT" softened to "not robust")?
- Are source-correction facts recorded (stale/wrong comments in code, wrong upstream docs) with error AND truth?
- Are gating/ordering preconditions recorded as rules ("X only after Y"), not as flat component lists?
- Are deliberately discarded follow-ups recorded so they are not rediscovered?
- Are skipped gates disclosed?
- Could a future agent continue the work from this artifact without rereading the full transcript?
- Would rerunning the deterministic scripts on the same input produce the same chunks and manifests?

## Recall Audit Protocol (Gate R)

Self-review is self-approving: the curator's criteria match what the curator happened to keep. For high-stakes curation:

1. Partition the source at episode boundaries.
2. One INDEPENDENT reviewer per segment (subagent when available; otherwise a fresh pass reading only raw segment + artifact). The reviewer inventories the segment's relevant facts and reports only MISSING/DISTORTED items with severity CRITICAL / USEFUL / NOISE.
3. Reviewers verify against the SOURCE, never against criteria written after curation.
4. Patch every CRITICAL and USEFUL finding into the JSONL; re-validate; re-render.
5. Report the scorecard (facts inventoried, losses by severity per artifact) in the final answer.

Calibration for reviewers: CRITICAL = a future session would act wrongly without it (wrong env, trusting a stale comment, missing gating precondition, lost estimates). Confirmatory command output for an already-captured fact = NOISE.

## Anchoring (do not orphan the artifact)

The curation only pays off if a future session finds it. Always finish by anchoring: pointer line in the project memory index (Claude Code `MEMORY.md`) or the environment's memory mechanism, linking the DIGEST (small, always safe to load). In pre-compact flows, the synchronous step captures cheaply (transcript + metadata + queue); full curation never runs inside a hook.

## Determinism

Deterministic:

- line counts, byte counts, hashes;
- marker inventory;
- chunk boundaries for the same source and parameters;
- JSONL validation results;
- Markdown rendered from the same JSONL.

Semantically stable but not byte-identical:

- Codex-authored summaries;
- grouping of adjacent chunks into episodes;
- wording of conclusions and risks.

To get byte-identical reruns, reuse the same curated JSONL as the canonical artifact, or compare future runs against it as a golden file and only accept intentional diffs.
