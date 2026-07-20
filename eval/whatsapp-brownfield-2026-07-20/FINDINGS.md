# Brownfield install eval — WhatsApp_Agent_Chat_slim-shape → orions-belt @ v1.6.3

**Date:** 2026-07-20 · **Harness ref:** v1.6.3 (8bd6708) · **Runner:** `eval/brownfield-install-eval.sh`
**Source repo:** `/home/augusto/code/WhatsApp_Agent_Chat_slim-shape` (1647 tracked files, 120 GB working tree — 119 GB is untracked `slimshape-agent/` runtime junk, excluded via `git clone --local`).
**Test clone:** `/home/augusto/code/WhatsApp_Agent_Chat_slim-shape-orions-belt-test`.

## Why this repo is a strong adversarial fixture
- Already carries an **earlier/parallel harness lineage**: skills `adversarial-review`, `marathon`, `curate-long-context`, `slimshape-delivery-council` (= `{{project_name}}-delivery-council`), plus `.claude/loop.md`, `docs/SCHEMA.md`, `docs/log.md`. → tests the collision path, not a clean greenfield.
- Uses the **pre-commit framework** (`.pre-commit-config.yaml`), a *different* hook manager than Husky.
- Python stack (pytest/ruff/mypy), tracked `AGENTS.md` + `.claude/CLAUDE.md` (42 KB) + `.gitignore`.

## Invariants — ALL HELD (raw logs: `*.stdout` / `*.stderr` / `*.sha256` in this dir)
| Invariant | Result | Evidence |
|---|---|---|
| Dry-run fail-closed on unowned collisions | ✅ exit 2, target untouched | `dryrun.stderr` (6–7 unowned paths), `git status` = 0 |
| Install proceeds with `--preserve` | ✅ `create=156, merge=3, preserve=7, unchanged=5` | `install.stdout` |
| Byte-a-byte preservation | ✅ of 1647 tracked, only 3 changed (AGENTS.md, .claude/CLAUDE.md, .gitignore = merge surfaces), 0 deleted | `baseline.sha256` vs `after.sha256` |
| Merge = append, not clobber | ✅ 1 marker each; original content precedes the harness block (109 / 529 / 46 lines) | `after.sha256` + marker grep |
| Idempotent reinstall | ✅ `preserve=7, unchanged=164`, 0 bytes changed | `reinstall.stdout` |
| Edit-abort on owned file | ✅ exit 2 "locally modified" | `editabort.stderr` |
| No `install-plan*` junk in target (G1) | ✅ 0 | `find` in the runner |

## FINDING A — pre-commit framework not detected → silent hook bypass  ✳ FIXED in v1.6.3+
- **Symptom (before fix):** the repo uses the pre-commit framework, which writes to `.git/hooks/pre-commit` and leaves `core.hooksPath` **empty**. The installer set `core.hooksPath=.githooks` with no acknowledgement — and git ignores `.git/hooks` once `core.hooksPath` is set, so the user's pre-commit hooks were **silently disabled**. `set_hooks_path.sh` only detected Husky + a pre-set `core.hooksPath`.
- **Severity:** MEDIA→ALTA in practice (pre-commit is the most common hook manager in Python repos).
- **Fix:** `set_hooks_path.sh` now detects `.pre-commit-config.yaml{,.yml}`; when `core.hooksPath` is empty it does **NOT** set it, and warns with the idiomatic integration (add a `repo: local` hook running `bash .githooks/pre-commit`, or opt in by hand). Regression: `templates/tests/test_set_hooks_path_precommit.sh` (3 cases). Greenfield/Husky behavior unchanged.

## Open friction (not a bug — documented)
- **Retroactive adoption:** the 7 harness-lineage collisions had no ownership manifest (they predate it / came from the Codex side), so the install forced `--preserve` on each. There is no "adopt these existing files as harness-owned" path yet — the user must choose preserve (keep theirs) or manually delete+reinstall (take the harness copy). This is the natural next capability for the co-development premise (two agents diverging the same skills).

## Reproduce
```bash
cd /home/augusto/code/harness-wiki
eval/brownfield-install-eval.sh /home/augusto/code/WhatsApp_Agent_Chat_slim-shape
```
