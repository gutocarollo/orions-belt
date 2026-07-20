#!/usr/bin/env python3
"""Plan and apply an orions-belt render without clobbering a brownfield repo.

The installer is intentionally independent from the target's Git index.  That
matters for agent surfaces such as .claude/, .codex/, .agents/ and AGENTS.md,
which are commonly local-only.  Every whole-file write is owned through a
content hash; the four shared surfaces use their semantic merge strategies.

Safety model:
  * inspect every destination before creating directories or files;
  * reject target symlinks and symlinked ancestors;
  * reject unknown collisions and locally-modified owned files;
  * compute every output before the first target mutation;
  * use same-directory atomic replace per file;
  * journal backups and roll back controlled failures.

This is recoverable, not a claim of filesystem-wide atomicity.  A process or
machine crash may leave the journal behind; the next invocation restores it
before planning a new operation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MANIFEST_VERSION = 1
MANIFEST_REL = Path(".harness/install-manifest.json")
JOURNAL_REL = Path(".harness/install-journal.json")
BACKUP_ROOT_REL = Path(".harness/install-backups")
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SENSITIVE: dict[str, str] = {
    "AGENTS.md": "marked-block",
    ".claude/CLAUDE.md": "marked-block",
    ".claude/settings.json": "structured-json",
    ".gitignore": "marked-block",
}


class InstallError(RuntimeError):
    """A fail-closed planning/apply error safe to show to the operator."""


@dataclass
class PlannedFile:
    rel: str
    source: Path
    destination: Path
    strategy: str
    action: str
    content: bytes
    mode: int
    previous_exists: bool
    previous_hash: str | None

    def public(self) -> dict[str, Any]:
        return {
            "path": self.rel,
            "strategy": self.strategy,
            "action": self.action,
            "previous_sha256": self.previous_hash,
            "next_sha256": sha256_bytes(self.content),
            "mode": oct(self.mode),
        }


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def settings_hook_commands(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    commands: set[str] = set()
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    for groups in hooks.values():
        if not isinstance(groups, list):
            raise ValueError("settings hook event must be a list")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("settings hook group must be an object with hooks list")
            for entry in group.get("hooks", []):
                if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                    commands.add(entry["command"])
    return sorted(commands)


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"{label} is unreadable or invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"{label} must be a JSON object: {path}")
    return value


def load_manifest(target: Path) -> dict[str, Any]:
    path = target / MANIFEST_REL
    if not path.exists():
        return {"version": MANIFEST_VERSION, "files": {}}
    if path.is_symlink():
        raise InstallError(f"ownership manifest is a symlink: {path}")
    manifest = load_json(path, "ownership manifest")
    if manifest.get("version") != MANIFEST_VERSION or not isinstance(manifest.get("files"), dict):
        raise InstallError(f"unsupported ownership manifest schema: {path}")
    return manifest


def _walk_target_parts(target: Path, rel: Path) -> None:
    """Reject any existing symlink/non-directory ancestor without following it."""
    current = target
    for part in rel.parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise InstallError(f"destination ancestor is a symlink: {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise InstallError(f"destination ancestor is not a directory: {current}")

    destination = target / rel
    try:
        info = destination.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise InstallError(f"destination is a symlink: {destination}")
    if not stat.S_ISREG(info.st_mode):
        raise InstallError(f"destination is not a regular file: {destination}")


def validate_rel(raw: str) -> Path:
    rel = Path(raw)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise InstallError(f"unsafe rendered path: {raw!r}")
    return rel


def source_files(scratch: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(scratch.rglob("*")):
        relative_parts = path.relative_to(scratch).parts
        if "__pycache__" in relative_parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise InstallError(f"render contains a symlink; explicit symlink ownership is unsupported: {path}")
        if path.is_file():
            files.append(path)
    return files


def load_merge_module(scratch: Path):
    module_path = scratch / ".harness/lib/merge_docs.py"
    if not module_path.is_file():
        raise InstallError(f"render is missing merge engine: {module_path}")
    spec = importlib.util.spec_from_file_location("orions_belt_merge_docs", module_path)
    if spec is None or spec.loader is None:
        raise InstallError(f"cannot load merge engine: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merged_content(
    merge_module: Any,
    rel: str,
    existing: Path,
    source: Path,
    workspace: Path,
    previous_owned_commands: set[str] | None = None,
) -> bytes:
    candidate = workspace / rel
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if existing.exists():
        shutil.copy2(existing, candidate)
    if rel in {"AGENTS.md", ".claude/CLAUDE.md"}:
        merge_module.merge_markdown(candidate, source, "harness-install")
    elif rel == ".gitignore":
        merge_module.merge_gitignore(candidate, source, "harness-install")
    elif rel == ".claude/settings.json":
        merge_module.merge_settings_json(candidate, source, previous_owned_commands)
    else:  # pragma: no cover - guarded by caller
        raise InstallError(f"no semantic merge strategy for {rel}")
    return candidate.read_bytes()


def build_plan(
    scratch: Path,
    target: Path,
    manifest: dict[str, Any],
    preserve_paths: set[str] | None = None,
) -> list[PlannedFile]:
    merge_module = load_merge_module(scratch)
    manifest_files: dict[str, Any] = manifest.get("files", {})
    preserve_paths = preserve_paths or set()
    plan: list[PlannedFile] = []
    conflicts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="orions-belt-plan-") as work_raw:
        workspace = Path(work_raw)
        for source in source_files(scratch):
            rel_path = validate_rel(source.relative_to(scratch).as_posix())
            rel = rel_path.as_posix()
            destination = target / rel_path
            _walk_target_parts(target, rel_path)

            exists = destination.exists()
            previous_hash = sha256_file(destination) if exists else None
            previous_mode = stat.S_IMODE(destination.stat().st_mode) if exists else None
            mode = stat.S_IMODE(source.stat().st_mode)
            strategy = SENSITIVE.get(rel, "owned")

            entry = manifest_files.get(rel)
            explicitly_preserved = rel in preserve_paths or (
                isinstance(entry, dict) and entry.get("strategy") == "preserve"
            )
            if explicitly_preserved:
                if not exists:
                    conflicts.append(f"{rel}: cannot preserve a path that does not exist")
                    continue
                strategy = "preserve"
                content = destination.read_bytes()
                mode = stat.S_IMODE(destination.stat().st_mode)
                action = "preserve"
            elif strategy != "owned":
                # Shared files belong partly to the project; preserve their
                # existing permission mode while reconciling only content.
                if previous_mode is not None:
                    mode = previous_mode
                try:
                    prior_commands = None
                    if rel == ".claude/settings.json" and isinstance(entry, dict):
                        inventory = entry.get("owned_hook_commands")
                        if isinstance(inventory, list) and all(isinstance(x, str) for x in inventory):
                            prior_commands = set(inventory)
                    content = merged_content(
                        merge_module, rel, destination, source, workspace, prior_commands
                    )
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    conflicts.append(f"{rel}: semantic merge failed: {exc}")
                    continue
                action = "unchanged" if exists and destination.read_bytes() == content else ("merge" if exists else "create")
            else:
                content = source.read_bytes()
                next_hash = sha256_bytes(content)
                if not exists:
                    action = "create"
                elif previous_hash == next_hash and previous_mode == mode:
                    # Safe adoption for installations predating the manifest.
                    action = "unchanged"
                elif previous_hash == next_hash:
                    # Bytes still prove exact ownership/adoption, but the
                    # executable/read mode drifted from the template contract.
                    action = "update"
                elif isinstance(entry, dict) and entry.get("strategy") == "owned":
                    if previous_hash == entry.get("last_applied_sha256"):
                        action = "update"
                    else:
                        conflicts.append(f"{rel}: locally modified since the last harness apply")
                        continue
                else:
                    conflicts.append(f"{rel}: existing path has no harness ownership record")
                    continue

            plan.append(
                PlannedFile(
                    rel=rel,
                    source=source,
                    destination=destination,
                    strategy=strategy,
                    action=action,
                    content=content,
                    mode=mode,
                    previous_exists=exists,
                    previous_hash=previous_hash,
                )
            )

    if conflicts:
        detail = "\n  - ".join(conflicts)
        raise InstallError(f"install plan has unowned/modified conflicts; target was not changed:\n  - {detail}")
    return plan


def manifest_for(plan: list[PlannedFile], previous: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    old_files = previous.get("files", {})
    rendered = {item.rel for item in plan}
    files: dict[str, Any] = {}
    for item in plan:
        file_entry = {
            "strategy": item.strategy,
            "type": "file",
            "last_applied_sha256": sha256_bytes(item.content),
            "mode": oct(item.mode),
        }
        if item.rel == ".claude/settings.json":
            try:
                file_entry["owned_hook_commands"] = settings_hook_commands(item.source)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise InstallError(f"cannot inventory owned settings hooks: {exc}") from exc
        files[item.rel] = file_entry
    # A removed template path is preserved until an explicit prune policy exists.
    for rel, entry in old_files.items():
        if rel not in rendered and isinstance(entry, dict):
            kept = dict(entry)
            kept["orphaned"] = True
            files[rel] = kept
    return {
        "version": MANIFEST_VERSION,
        "template": metadata,
        "files": files,
    }


def _journal_path(target: Path) -> Path:
    return target / JOURNAL_REL


def _remove_empty_parents(path: Path, target: Path) -> None:
    """Remove only empty directories created by this apply, never user data."""
    current = path
    while current != target:
        try:
            current.rmdir()
        except (FileNotFoundError, OSError):
            return
        current = current.parent


def recover(target: Path) -> bool:
    journal_path = _journal_path(target)
    if not journal_path.exists():
        return False
    _walk_target_parts(target, JOURNAL_REL)
    journal = load_json(journal_path, "install journal")
    if journal.get("version") != 1:
        raise InstallError(f"unsupported install journal schema: {journal_path}")
    backup_raw = journal.get("backup_root")
    if not isinstance(backup_raw, str):
        raise InstallError(f"journal backup_root must be a string: {journal_path}")
    backup_root = Path(backup_raw)
    run_id = backup_root.name
    expected = target / BACKUP_ROOT_REL / run_id
    if (
        not backup_root.is_absolute()
        or any(part == ".." for part in backup_root.parts)
        or not RUN_ID_RE.fullmatch(run_id)
        or backup_root != expected
    ):
        raise InstallError(
            "journal backup path must be the exact managed run directory "
            f"{target / BACKUP_ROOT_REL}/<uuid>: {backup_root}"
        )
    # Check every ancestor with lstat before resolve/rmtree. A symlink anywhere
    # under .harness/install-backups would otherwise turn a target-local string
    # into an external deletion target.
    _walk_target_parts(target, BACKUP_ROOT_REL / run_id / ".recovery-sentinel")
    if not backup_root.is_dir() or backup_root.is_symlink():
        raise InstallError(f"journal backup directory is missing or unsafe: {backup_root}")
    backup_root_resolved = backup_root.resolve(strict=True)
    if backup_root_resolved != expected:
        raise InstallError(f"journal backup directory does not resolve exactly as managed: {backup_root}")

    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise InstallError(f"install journal has invalid entries: {journal_path}")
    seen_entries: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
            raise InstallError(f"install journal has an invalid entry: {journal_path}")
        rel = validate_rel(str(entry.get("path", "")))
        rel_string = rel.as_posix()
        if (
            rel_string in seen_entries
            or rel == JOURNAL_REL
            or rel == BACKUP_ROOT_REL
            or BACKUP_ROOT_REL in rel.parents
        ):
            raise InstallError(f"install journal has a duplicate/reserved entry: {rel_string}")
        try:
            int(str(entry.get("mode", "")), 8)
        except ValueError as exc:
            raise InstallError(f"install journal has an invalid mode for {rel_string}") from exc
        seen_entries.add(rel_string)
    for entry in reversed(entries):
        rel = validate_rel(str(entry["path"]))
        destination = target / rel
        _walk_target_parts(target, rel)
        if entry.get("existed"):
            backup = backup_root / rel
            _walk_target_parts(backup_root, rel)
            if not backup.is_file() or backup.is_symlink():
                raise InstallError(f"journal backup is missing or unsafe: {backup}")
            atomic_write(destination, backup.read_bytes(), int(entry.get("mode", "0o644"), 8))
        elif destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise InstallError(f"refusing to remove unexpected recovery target: {destination}")
            destination.unlink()

    shutil.rmtree(backup_root, ignore_errors=True)
    journal_path.unlink(missing_ok=True)
    for entry in entries:
        rel = validate_rel(str(entry["path"]))
        _remove_empty_parents((target / rel).parent, target)
    _remove_empty_parents(backup_root.parent, target)
    _remove_empty_parents(journal_path.parent, target)
    return True


def apply_plan(
    plan: list[PlannedFile],
    target: Path,
    manifest: dict[str, Any],
    fail_after: int | None = None,
) -> None:
    run_id = uuid.uuid4().hex
    backup_root = target / BACKUP_ROOT_REL / run_id
    backup_root.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []

    manifest_path = target / MANIFEST_REL
    all_backups: list[tuple[str, Path, bool, int]] = []
    for item in plan:
        if item.action in {"unchanged", "preserve"}:
            continue
        old_mode = stat.S_IMODE(item.destination.stat().st_mode) if item.previous_exists else item.mode
        all_backups.append((item.rel, item.destination, item.previous_exists, old_mode))
    all_backups.append((MANIFEST_REL.as_posix(), manifest_path, manifest_path.exists(), 0o644))

    try:
        for rel, destination, existed, old_mode in all_backups:
            if existed:
                backup = backup_root / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            entries.append({"path": rel, "existed": existed, "mode": oct(old_mode)})

        journal = {
            "version": 1,
            "backup_root": str(backup_root),
            "entries": entries,
        }
        atomic_write(_journal_path(target), (json.dumps(journal, indent=2) + "\n").encode())
    except BaseException:
        # No target payload was written yet and no valid journal was published.
        # Remove only this freshly-created, exact UUID backup directory.
        shutil.rmtree(backup_root, ignore_errors=True)
        _remove_empty_parents(backup_root.parent, target)
        _remove_empty_parents(_journal_path(target).parent, target)
        raise

    writes = 0
    try:
        for item in plan:
            if item.action in {"unchanged", "preserve"}:
                continue
            _walk_target_parts(target, validate_rel(item.rel))
            atomic_write(item.destination, item.content, item.mode)
            writes += 1
            if fail_after is not None and writes >= fail_after:
                raise InstallError(f"injected failure after {writes} writes")

        manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        atomic_write(manifest_path, manifest_bytes)
    except BaseException:
        recover(target)
        raise
    else:
        shutil.rmtree(backup_root, ignore_errors=True)
        _journal_path(target).unlink(missing_ok=True)


def plan_document(plan: list[PlannedFile], target: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in plan:
        counts[item.action] = counts.get(item.action, 0) + 1
    return {
        "target": str(target),
        "counts": counts,
        "files": [item.public() for item in plan],
    }


def parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"invalid --metadata-json: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallError("--metadata-json must be a JSON object")
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-json", type=Path)
    parser.add_argument("--metadata-json")
    parser.add_argument("--preserve", action="append", default=[], metavar="RELATIVE_PATH")
    args = parser.parse_args(argv)

    try:
        scratch = args.scratch.resolve(strict=True)
        target_input = args.target.absolute()
        if target_input.is_symlink():
            raise InstallError(f"target root is a symlink: {target_input}")
        target = target_input.resolve(strict=True)
        if not target.is_dir():
            raise InstallError(f"target is not a directory: {target}")

        if args.plan_json:
            plan_output = args.plan_json.absolute()
            resolved_plan_output = plan_output.resolve(strict=False)
            try:
                resolved_plan_output.relative_to(target)
            except ValueError:
                pass
            else:
                raise InstallError(
                    "--plan-json must be outside the target so dry-run cannot mutate it: "
                    f"{plan_output} -> {resolved_plan_output}"
                )

        if recover(target):
            print("install_apply: recovered an incomplete previous apply", file=sys.stderr)

        manifest = load_manifest(target)
        preserve_paths = {validate_rel(raw).as_posix() for raw in args.preserve}
        plan = build_plan(scratch, target, manifest, preserve_paths)
        public_plan = plan_document(plan, target)
        encoded_plan = json.dumps(public_plan, indent=2, ensure_ascii=False) + "\n"
        if args.plan_json:
            plan_output.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(plan_output, encoded_plan.encode())
        print(encoded_plan, end="")
        if not args.dry_run:
            next_manifest = manifest_for(plan, manifest, parse_metadata(args.metadata_json))
            injected = os.environ.get("ORIONS_BELT_FAIL_AFTER")
            apply_plan(plan, target, next_manifest, int(injected) if injected else None)
        return 0
    except (InstallError, OSError, ValueError) as exc:
        print(f"install_apply: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
