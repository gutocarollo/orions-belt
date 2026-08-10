#!/usr/bin/env python3
"""Explicit lifecycle for activating and finishing an enforceable Council run."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from council_runtime import apply_transition

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def worktree_state(root: Path) -> list[str]:
    command = [
        "git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".",
        ":(exclude).harness/runs/**", ":(exclude).harness/council-active",
        ":(exclude).harness/council-active.required-next",
    ]
    return sorted(item for item in subprocess.check_output(command, cwd=root, text=True).split("\0") if item)


def start_session(
    root: Path,
    run_id: str,
    anchor_source: str,
    mutation_mode: str = "WORKSPACE_WRITE",
    execution_graph: Path | None = None,
    context_required: bool | None = None,
) -> Path | None:
    if mutation_mode == "READ_ONLY":
        return None
    if execution_graph is not None and not execution_graph.is_absolute():
        execution_graph = root / execution_graph
    if execution_graph is None or not execution_graph.is_file():
        raise RuntimeError("writable Council session requires --execution-graph")
    try:
        graph = json.loads(execution_graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"execution graph is unreadable: {execution_graph}") from exc
    folder = root / ".harness/runs/agent-swarm" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if context_required is None:
        context_required = (root / ".harness/context-delivery.enabled").is_file()
    event = {
        "seq": 1,
        "event": "ANCHOR",
        "payload": {
            "mutation_mode": mutation_mode,
            "anchor_source": anchor_source,
            "context_required": bool(context_required),
            "base_sha": base_sha,
            "worktree_baseline": worktree_state(root),
            "execution_graph": graph,
        },
    }
    state = apply_transition(None, event["event"], event["payload"], repository_root=root)
    (folder / "council-events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    state_path = (folder / "council-state.json").resolve()
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pointer = root / ".harness/council-active"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(state_path) + "\n", encoding="utf-8")
    run_folder = root / ".harness/runs" / run_id
    run_folder.mkdir(parents=True, exist_ok=True)
    run_path = run_folder / "RUN.md"
    if not run_path.exists():
        run_path.write_text(
            f"# Council run: {run_id}\n\nAnchor: `{anchor_source}`\n\n## Pendências não bloqueantes\n\n- Nenhuma no início do run.\n",
            encoding="utf-8",
        )
    (root / ".harness/runs/ACTIVE").write_text(run_id + "\n", encoding="utf-8")
    hooks_dir = Path(subprocess.check_output(["git", "rev-parse", "--git-path", "hooks"], cwd=root, text=True).strip())
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / "pre-push"
    if target.exists() and target.read_bytes() != (SOURCE_ROOT / ".githooks/pre-push").read_bytes():
        raise RuntimeError(f"existing pre-push hook differs: {target}")
    shutil.copy2(SOURCE_ROOT / ".githooks/pre-push", target)
    target.chmod(0o755)
    return state_path


def finish_session(root: Path) -> None:
    pointer = root / ".harness/council-active"
    if not pointer.is_file():
        raise RuntimeError("no active Council session")
    state_path = Path(pointer.read_text(encoding="utf-8").strip())
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("stage") != "DELIVERY":
        raise RuntimeError("Council session cannot finish before DELIVERY")
    pointer.unlink()
    active = root / ".harness/runs/ACTIVE"
    if active.is_file() and active.read_text(encoding="utf-8").strip() == state_path.parent.name:
        active.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--root", type=Path, default=Path.cwd())
    start.add_argument("--run-id", required=True)
    start.add_argument("--anchor-source", required=True)
    start.add_argument("--mutation-mode", choices=("READ_ONLY", "WORKSPACE_WRITE"), default="WORKSPACE_WRITE")
    start.add_argument("--execution-graph", type=Path)
    start.add_argument(
        "--context-required",
        choices=("auto", "required", "off"),
        default="auto",
        help="auto follows the rendered capability marker; required/off are explicit overrides",
    )
    finish = commands.add_parser("finish")
    finish.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.command == "start":
        context_required = None if args.context_required == "auto" else args.context_required == "required"
        state = start_session(
            args.root.resolve(), args.run_id, args.anchor_source,
            args.mutation_mode, args.execution_graph, context_required,
        )
        print(state if state else "INLINE_READ_ONLY")
    else:
        finish_session(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
