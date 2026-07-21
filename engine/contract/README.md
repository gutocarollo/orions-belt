# engine/contract — executable enforcement layer

Port of the `agent-swarm` enforcement stack (`codex/{schemas,scripts,tests,verification}/` —
see `docs/planning/research/02-agent-swarm.md` and `docs/planning/00-plano-consolidado.md` §3/§6 F1)
into the agent-harness engine. Four layers, pure stdlib (zero external dependency):

1. **Schemas** (`schemas/*.schema.json`) — JSON Schema (draft 2020-12) for the structured
   payloads that an adversarial review produces: `plan-review-result.schema.json`,
   `execution-review-result.schema.json` (enums `SATISFEITO|REPLANEJAR|BLOQUEADO` and
   `SATISFEITO|CORRIGIR|BLOQUEADO`, with `allOf`/`if`/`then` requiring `replan_request`/
   `fix_request` when the verdict is not satisfied) and `ledger-event.schema.json` (the shape of
   a ledger event). Ported unchanged — they were already generic.
2. **Witness** (`verification/witness-fixes.json` + `scripts/verify_witness.py`) — load-bearing
   text markers: each `fix` declares a `file`+`marker` that MUST exist literally in the
   file. `verify_witness.py --witness <path>` fails if the marker disappeared (protection against
   silent regression of content that nobody tests via a behavior assertion).
3. **Ledger** (`scripts/agent_swarm_ledger.py`) — append-only JSONL log of loop events
   (`review`, `replan-request`, `replan-consumed`, `fix-request`, `fix-consumed`, `validation`,
   `final`) per `run_id`, with a `summary` subcommand aggregating counts and the last status per loop.
4. **Contract tests** (`tests/test_agent_contract.py`, `unittest`) — regression suite that
   protects the invariants above and the generated ends (schemas parse, agent TOML/YAML
   parses, the `assert_payload_block` helper works, the NEGATIVE witness test fails when the
   marker does not exist).

`scripts/validate_contract.py` is the single entry point: it validates the `.json` files in
`schemas/`+`verification/`, runs `validate_skills.py`, runs `verify_witness.py`, runs
`unittest discover -s tests`, and (unless `--skip-git-check`) runs `git diff --check`.
**Nao ha GitHub Actions neste pacote** — validation is local/manual, invoked via
`python3 engine/contract/scripts/validate_contract.py`.

## What was PARAMETERIZED in this round (F1)

Explicit instruction of the plan: replace hardcode with reading `.harness/harness.conf` via
`engine/_tooling_conf.py`, without duplicating the parser.

| Script | Original hardcode | Config key (default = original value) |
|---|---|---|
| `validate_skills.py` | `SKILL_DIR = ROOT/".agents"/"skills"` | `HARNESS_SKILLS_DIR` |
| `validate_skills.py` | `REQUIRED_SKILLS = ("learnhouse-delivery-council", "adversarial-review", "clarification-plan")` | `HARNESS_REQUIRED_SKILLS` (CSV; obrigatório quando skills/Codex estão instalados) |
| `validate_skills.py` | `.codex/agents`, `.codex/config.toml` | `HARNESS_CODEX_AGENTS_DIR`, `HARNESS_CODEX_CONFIG_PATH` (fail-open skip if `.codex/` does not exist — Claude-only project) |
| `validate_skills.py` | `openai.yaml` of `learnhouse-delivery-council` fixed | `HARNESS_COUNCIL_SKILL_NAME` (obrigatório quando Codex está instalado) |
| `agent_swarm_ledger.py` | `RUNS_DIR = ROOT/".agent-swarm"/"runs"` | `HARNESS_LEDGER_DIR` (default `${HARNESS_RUNS_DIR}/agent-swarm` — reuses marathon's run-state dir instead of a second root directory) |
| `render_prompt.py` | line 1 `"Use $learnhouse-delivery-council."` | `HARNESS_COUNCIL_SKILL_NAME` (fallback `delivery-council`) |

`validate_contract.py` and `verify_witness.py` were NOT parameterized to point at a
target project — on purpose. They are **self-referential**: they protect the content of
`engine/contract/` ITSELF (that this `validate_contract.py` is intact, that the witness markers
still exist in this package's files), not the content of an installed project. `ROOT =
Path(__file__).resolve().parents[1]` remains correct for both. By contrast, `validate_skills.py` and
`agent_swarm_ledger.py` validate/write **target project** state, so they use
`_tooling_conf.project_root()` (`HARNESS_PROJECT_ROOT` -> `CLAUDE_PROJECT_DIR` -> `git
rev-parse --show-toplevel` -> cwd).

## What was NOT ported in round F1 (deferred to F1.5 — already completed)

The original `witness-fixes.json` had 9 entries; 7 pointed to **council** content
(pipeline in `README.md`, `REPLAN-REQUEST`/`FIX-REQUEST` sentinels in
`.agents/skills/learnhouse-delivery-council/SKILL.md`, final gates) — files that did not yet
exist in this layout because the merge of the 2 council lineages (learnhouse `.claude/skills/
learnhouse-delivery-council/SKILL.md` × agent-swarm `.agents/skills/learnhouse-delivery-council/
SKILL.md`) was **F1.5** (`docs/planning/00-plano-consolidado.md` §6 F1.5 and §3 "Merge of the 2
council lineages"), not F1. In round F1, `verification/witness-fixes.json` was left with only the
2 entries whose marker survived in what had actually been ported (`TEST-PAYLOAD-SCOPE-001`,
`LOCAL-CONTRACT-001`) and 7 tests in `tests/test_agent_contract.py` were `@unittest.skip(...)`.

**F1.5 completed** (same session): real merge in `templates/.agents/skills/
{{ project_name }}-delivery-council/SKILL.md.jinja` + `templates/.agents/skills/adversarial-review/
SKILL.md.jinja` + `templates/{% if use_codex %}.codex{% endif %}/agents/{{ project_name }}-adversarial-reviewer.toml.jinja`
(post-F3-restructure paths — `templates/` mirrors the target project root directly, without a
`claude/`/`codex/`/`shared/` wrapper), with the pattern "REPLAN/FIX-REQUEST+CONSUMED (agent-swarm
lineage) merged with mandatory-subagent+REVISORES+SendMessage (learnhouse lineage)". Its own witness in
`templates/verification/council-witness.json` (6 markers, `verify_witness.py --root
templates` — new `--root` flag, a minimal generalization that preserves this package's
self-referential default). 5 of the 7 skipped tests were REACTIVATED with adapted paths in
`templates/tests/test_council_merge.py` (near the merged content, not here — see the note
at the top of the test file). The remaining 2 (`test_readme_has_single_ordered_pipeline_with_real_loops`,
`test_historical_plan_doc_is_marked_non_canonical`) stay skipped: they depend on a README with a
mermaid pipeline diagram (F7/case-study scope) and on `docs/PLANO-SWARM.md` (a historical doc
specific to the original agent-swarm, with no equivalent here) — neither belongs to the merge of
SKILL.md itself.
