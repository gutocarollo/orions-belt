#!/usr/bin/env python3
"""install_report.py — emit the install DECISION REPORT as an audit artifact.

Every (re)install regenerates `<target>/.harness/INSTALL-REPORT.md`: what the
installer decided to install and what it did NOT, each with the reason and an
APPLIED example (tied to this repo's real paths/flags), so a human can audit the
outcome without diffing the tree. It reads only what the install already
produced — the ownership manifest (per-file strategy) and the answers file (the
flags that gated each component). It invents nothing.

Usage: install_report.py --target <dir> [--timestamp <str>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def load_answers(target: Path) -> dict:
    """Minimal YAML scalar reader for .harness/answers.yml (flat key: value)."""
    answers: dict[str, object] = {}
    path = target / ".harness/answers.yml"
    if not path.is_file():
        return answers
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith((" ", "\t", "#", "_")) or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip().strip("'\"")
        if raw in {"true", "false"}:
            answers[key.strip()] = raw == "true"
        else:
            answers[key.strip()] = raw
    return answers


def flag(answers: dict, name: str, default=False):
    return answers.get(name, default)


# Each conditional component: the flag that gates it, why it exists, and an
# applied example phrased for BOTH outcomes. `{web}` etc. interpolate real values.
COMPONENTS = [
    ("Claude Code surface (.claude/)", "use_claude",
     "Renders CLAUDE.md, .claude/skills and settings.json hooks for Claude Code.",
     "Claude reads .claude/CLAUDE.md; without this flag the whole .claude/ tree is skipped.",
     True),
    ("Codex surface (.agents/, .codex/, AGENTS.md)", "use_codex",
     "Renders AGENTS.md, .agents/skills and .codex config/hooks for Codex.",
     "Codex reads AGENTS.md + .agents/skills; without this flag none of it is written.",
     True),
    ("UI-evidence gate", "use_ui_evidence",
     "Stop hook forcing before/after Playwright PNGs for visual changes.",
     "With it ON, editing {web}/app/*.tsx would block the turn until a PNG manifest exists; OFF means front-end changes ship without that proof.",
     False),
    ("Design-system gate (ds-gate ratchet + colour-pair check)", "use_ds_gate",
     "PostToolUse hook + ratchet blocking hardcoded colours / failing token pairs.",
     "With it ON, adding a raw gray-500 in {web} trips the ratchet; OFF means no token discipline is enforced.",
     False),
    ("Icon guard", "use_icon_guard",
     "hookify rule steering icon imports to the chosen library.",
     "With it ON, importing from the wrong icon set is flagged; OFF means icon imports are unchecked.",
     False),
    ("UI skills (component playbook / responsive / classname workflow)", "use_ui_skills",
     "Front-end authoring skills.",
     "Useful only for a repo with a UI; OFF avoids dead skills in a back-end-only project.",
     False),
    ("Data-warehouse dashboards", "use_data_warehouse",
     "Bklit/dashboard skills.",
     "ON only when the project ships analytics dashboards; OFF keeps the skill set lean.",
     False),
    ("GitHub CI helpers", "use_github_ci",
     "CI-oriented scaffolding.",
     "ON for repos using GitHub Actions; OFF otherwise.",
     False),
]


def deploy_status(answers: dict) -> tuple[bool, str, str]:
    has_prod = flag(answers, "has_prod_stack")
    driver = str(answers.get("prod_deployment_driver", "") or "")
    if has_prod and driver == "swarm-direct":
        return (True, f"has_prod_stack=true, prod_deployment_driver={driver}",
                "Swarm-direct guards (prune/destroy/push/monitor/image-source) + the deploy skill are installed because you drive prod directly.")
    reason = f"has_prod_stack={str(has_prod).lower()}" + (f", prod_deployment_driver={driver}" if driver else "")
    example = ("EasyPanel/managed drivers stay fail-closed: mutating Swarm commands would be plausible-but-wrong, so no deploy skill/guards are written."
               if has_prod else "No production stack declared, so no deploy skill or prod guards are generated.")
    return (False, reason, example)


def run_status(answers: dict) -> tuple[bool, str, str]:
    cmd = str(answers.get("harness_run_command", "") or "")
    proj = answers.get("project_name", "project")
    if cmd:
        return (True, f"harness_run_command={cmd!r}",
                f"The run-{proj} skill wraps `{cmd}` to bring the dev stack up.")
    return (False, "harness_run_command is empty",
            f"No run-{proj} skill is generated — the installer refuses to invent an apps/web|apps/api stack it cannot verify.")


def hook_manager_decision(target: Path) -> tuple[str, str]:
    has_precommit = (target / ".pre-commit-config.yaml").is_file() or (target / ".pre-commit-config.yml").is_file()
    has_husky = (target / ".husky/pre-commit").exists()
    try:
        hp = subprocess.run(["git", "-C", str(target), "config", "--get", "core.hooksPath"],
                            capture_output=True, text=True).stdout.strip()
    except Exception:
        hp = ""
    if hp == ".githooks":
        return ("core.hooksPath -> .githooks (harness ref-integrity active)",
                "No conflicting hook manager was detected, so the harness pre-commit is active.")
    if has_husky:
        return ("core.hooksPath NOT set — Husky detected",
                "Husky owns the hooks; re-run with --chain-hooks to add the harness pre-commit without displacing it.")
    if has_precommit:
        return ("core.hooksPath NOT set — pre-commit framework detected (.pre-commit-config.yaml)",
                "Setting core.hooksPath would make git ignore .git/hooks/pre-commit and silently disable your hooks; add a `repo: local` hook running .githooks/pre-commit, or set core.hooksPath yourself.")
    return (f"core.hooksPath = {hp or 'unset'}",
            "Reported as-is; the harness never overwrites an existing hook manager (A2, anti-clobber).")


STRATEGY_DESC = {
    "owned": ("Fully harness-controlled files. Editing one makes the next install abort ('locally modified') until you revert — that is how the harness stays authoritative without clobbering surprises.",),
    "marked-block": ("Your file was KEPT; the harness block was appended below an `orions-belt:begin` marker (append, never overwrite). Your original content survives verbatim above it.",),
    "structured-json": ("Structured merge (e.g. settings.json): your keys are preserved; the harness hooks are merged by identity, so re-installs never duplicate them.",),
    "preserve": ("A collision you explicitly chose to keep with --preserve: YOUR copy won and the harness did NOT write its version. To adopt the harness version instead, delete the path and reinstall.",),
    "seed": ("Created from the harness on first install, then project-owned living knowledge. Updates preserve the project's bytes and never fail because the file evolved locally.",),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--timestamp", default=None)
    args = ap.parse_args()
    target = Path(args.target).resolve()

    manifest = json.loads((target / ".harness/install-manifest.json").read_text(encoding="utf-8"))
    answers = load_answers(target)
    files = manifest.get("files", {})
    tmpl = manifest.get("template", {})
    ts = args.timestamp or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    proj = answers.get("project_name", "?")
    runtimes = ", ".join([r for r, f in (("Claude Code", "use_claude"), ("Codex", "use_codex")) if flag(answers, f)]) or "none"

    out: list[str] = []
    w = out.append
    w(f"# orions-belt install report — {proj}\n")
    w(f"- **Generated:** {ts}")
    w(f"- **Template:** `{tmpl.get('ref','?')}` from {tmpl.get('source','?')}")
    w(f"- **Runtimes:** {runtimes}")
    w(f"- **Language:** {answers.get('harness_language','?')}\n")
    w("> Audit trail of what this install decided to install and what it did NOT, with the reason and an\n"
      "> applied example. Regenerated on every (re)install. Derived only from the ownership manifest and\n"
      "> the answers file — nothing here is invented.\n")

    web = str(answers.get("harness_web_app_dir", ".") or ".")

    w("## 1. Components — installed / skipped & why\n")
    w("| Component | Decision | Gated by | Reason & applied example |")
    w("|---|---|---|---|")
    for name, fl, reason, example, default in COMPONENTS:
        on = flag(answers, fl, default)
        mark = "✅ installed" if on else "⛔ skipped"
        w(f"| {name} | {mark} | `{fl}={str(on).lower()}` | {reason} — *{example.format(web=web)}* |")
    d_on, d_reason, d_ex = deploy_status(answers)
    w(f"| Deploy skill + prod guards | {'✅ installed' if d_on else '⛔ skipped'} | `{d_reason}` | {d_ex} |")
    r_on, r_reason, r_ex = run_status(answers)
    w(f"| Dev-stack run skill | {'✅ installed' if r_on else '⛔ skipped'} | `{r_reason}` | {r_ex} |")
    w("")

    w("## 2. File-level decisions (from the ownership manifest)\n")
    by_strategy: dict[str, list[str]] = {}
    for path, entry in files.items():
        by_strategy.setdefault(entry.get("strategy", "?"), []).append(path)
    for strat in ("owned", "marked-block", "structured-json", "seed", "preserve"):
        paths = sorted(by_strategy.get(strat, []))
        if not paths:
            continue
        desc = STRATEGY_DESC.get(strat, ("",))[0]
        w(f"### {strat} — {len(paths)} file(s)")
        w(desc)
        example_paths = paths if strat in {"marked-block", "preserve", "structured-json", "seed"} else paths[:3]
        w("Applied example — " + ("these exact files" if strat in {"marked-block", "preserve", "structured-json", "seed"} else "e.g.") + ":")
        for p in example_paths:
            w(f"- `{p}`")
        if strat not in {"marked-block", "preserve", "structured-json", "seed"} and len(paths) > 3:
            w(f"- …and {len(paths)-3} more.")
        w("")

    w("## 3. Hook manager\n")
    hp_decision, hp_example = hook_manager_decision(target)
    w(f"- **Decision:** {hp_decision}")
    w(f"- **Why / applied example:** {hp_example}\n")

    w("## 4. Not installed — one-glance summary\n")
    skipped = [name for name, fl, *_rest in COMPONENTS if not flag(answers, fl, _rest[-1])]
    if not d_on:
        skipped.append("Deploy skill + prod guards")
    if not r_on:
        skipped.append("Dev-stack run skill")
    if skipped:
        for s in skipped:
            w(f"- ⛔ {s}")
    else:
        w("- (nothing skipped — every conditional component was installed)")
    w("")

    report = "\n".join(out) + "\n"
    dest = target / ".harness/INSTALL-REPORT.md"
    dest.write_text(report, encoding="utf-8")
    print(str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
