# Council macro-objective upgrade — delivery report

## Outcome

The Council now treats the requested macro outcome as the controlling north. Interview, clarification and review findings are scored with the executable weighted model before they can block work. Only `CRITICAL_BLOCK` and `HIGH_FIX_NOW` enter the current correction loop; `DEFER_RUN` is persisted in `RUN.md` and execution continues.

Planning is a directed START-to-GOAL graph. Every critical edge carries stable functional, quality and regression test IDs. `planning-and-task-breakdown` runs before every phase, item and reviewer correction; `incremental-implementation` governs every edit and requires a validated local commit per slice. Push and remote-main merge remain separately authorized actions.

## Critical journey coverage

The machine-readable graph is `execution-graph.json`. It covers objective control, graph-bound planning/execution, proof, dual-runtime portability, independent review and authorized publication. The delivery pipeline rejects:

- a code-necessity report with identical base/head SHAs;
- a critical branch missing from acceptance;
- test IDs not carried by the exact command;
- declared commands that fail when replayed at delivery;
- a reused slice SHA;
- any code-changing commit absent from the ledger, including merge resolutions;
- blobs differing from the validated file hashes;
- worktree drift after the run baseline;
- one thread acting as both quality and adversarial reviewer;
- `SIMPLIFICATION: APLICAR` without a new plan, validation, local commit, quality review and final `NAO_NECESSARIA` pass.

## Skills integrated into the Council path

Both `.claude` and `.agents` renders include the same operating contract for:

- `adversarial-review`
- `clarification-plan`
- `interview-me`
- `planning-and-task-breakdown`
- `incremental-implementation`
- `test-driven-development`
- `prova-de-conclusao`
- `verify`
- `code-review-and-quality`
- `code-simplification`
- the generated delivery Council

## Deterministic evidence

Fresh rendered installation at receipt commit `15a3d64`, covering code through
`0546f4b`:

- objective control: 11/11 PASS;
- runtime: 20/20 PASS;
- delivery pipeline: 19/19 PASS;
- contract: 19/19 PASS;
- evaluator and real scenarios: 3/3 PASS;
- total rendered Python checks: 72/72 PASS;
- template merge checks: 10/10 PASS;
- Claude-only, Codex-only and dual-runtime PT/EN render matrix: PASS;
- `.claude`/`.agents` operating skills: byte-identical in dual-runtime render;
- donor-brand leakage check: zero hits.

Tengwar’s installed runtime additionally passed 21/21 state-machine tests and 10/10 pipeline tests after the final merge-provenance correction.

## Independent quality loop

Quality reviewer thread: `019fe5ba-cf76-76b3-937e-43d8b0c0ba8d`.

The first round reproduced four proof gaps. The second round reproduced reused slice SHAs, unrecorded code commits and declared-only commands. The third round found merge-resolution provenance. All blocking findings were corrected and rechecked in the same thread.

The latest quality recheck reproduced one proof-provenance gap: the command
receipts and commit ledger stopped at `0f4b144`. After both were refreshed, the
same thread matched the executable code history 16/16 and returned
`QUALITY-REVIEW: SATISFEITO` with zero critical gaps.

The first independent adversarial round reproduced three critical and two high gaps:
invalid EN lifecycle commands, a direct read-only write bypass, lost planning
deferrals, narrative-only edge evidence and unverified code-necessity prose.
Those corrections are captured in commits `f98a62a` through `0f4b144`.

A later substitute adversarial reviewer reproduced three additional critical
gaps after the original thread became operationally unresponsive: self-assigned
graph impact, PHASE-PLAN nodes not bound to delivered edges, and evidence that
accepted negative review files while excluding executable Jinja templates.
Commits `37c6b12`, `71cc8d1` and `0546f4b` close those probes; independent
quality, simplification and adversarial rechecks are required before E6.

## Simplification and line necessity

Across `e373cce..0546f4b`, executable code and Jinja templates contain 1,720
added lines. Every added line is covered by 66 semantic portions in
`code-necessity.json`; the largest portion is 120 lines. Each portion carries a repository path, bounded source
range, objective, inputs, outputs and a command that the validator resolves at
the bound SHA and executes. Four distinct nontrivial proof commands passed.

The previous simplification verdict identified five concrete gaps; four code or
proof-integrity gaps are now corrected and the fifth is the authorized
publication artifact still pending. The same reviewer returned
`SIMPLIFICATION: NAO_NECESSARIA`, zero gaps. The current mechanisms correspond
one-to-one to reproduced bypasses:
read-only rejection, planning deferral persistence, executable evidence receipts
and a reusable rendered-runtime harness.

## Local commit chain

Orion’s Belt commits, oldest to newest:

- `0d2c42c` — macro-objective delivery control;
- `d356215` — operating-skill rendering;
- `647491d` — locale-safe impact markers;
- `a489a54`, `3584ab0` — current code-receipt semantics;
- `5e291ab` — proof bound to execution;
- `95dbfd4` — commit and command provenance;
- `7b9a02e` — code-changing merge provenance.
- `f98a62a` — read-only, planning deferral and EN lifecycle corrections;
- `02c6f63` — executable code-necessity evidence;
- `0d59764` — rendered-runtime proof harness;
- `0f4b144` — path-normalized cross-render parity.
- `324516b` — valid EN simplification vocabulary;
- `ef39d2c` — read-only append rejection;
- `5e4c429` — post-replay repository integrity;
- `febf660` — granular necessity receipts;
- `979c825` — real Council lifecycle in the parity test.
- `37c6b12` — graph-bound blockers and phase plans;
- `71cc8d1` — executable Jinja provenance;
- `0546f4b` — structured impact evidence and terminal review semantics.

Tengwar remains local-only for this task. The Orion’s Belt branch is the authorized publication target. No merge to remote `main` is authorized.

## Publication state

At report creation the branch is release-ready. Push and PR creation are the remaining authorized delivery actions; the PR URL is recorded in the final handoff after GitHub confirms it. Merge remains explicitly out of scope.
