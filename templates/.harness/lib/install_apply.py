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

This is recoverable, not a claim of filesystem-wide or power-loss atomicity.
A killed process may leave the journal behind; the next invocation validates
and restores it before planning a new operation.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
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
JOURNAL_VERSION = 2
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
    previous_mode: int | None

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


def settings_hook_identities(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    identities: set[str] = set()
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError("settings hook event must be a list")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("settings hook group must be an object with hooks list")
            group_scope = {key: value for key, value in group.items() if key != "hooks"}
            for entry in group.get("hooks", []):
                if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                    identities.add(json.dumps(
                        {"event": event, "group": group_scope, "command": entry["command"]},
                        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                    ))
                elif not isinstance(entry, dict):
                    raise ValueError("settings hook entries must be objects")
    return sorted(identities)


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


def target_identity(target: Path) -> tuple[int, int]:
    anchored = str(target).startswith("/proc/self/fd/")
    info = target.stat() if anchored else target.lstat()
    if (not anchored and stat.S_ISLNK(info.st_mode)) or not stat.S_ISDIR(info.st_mode):
        raise InstallError(f"target root is no longer a real directory: {target}")
    return info.st_dev, info.st_ino


def assert_target_identity(target: Path, expected: tuple[int, int]) -> None:
    try:
        actual = target_identity(target)
    except OSError as exc:
        raise InstallError(f"target root disappeared during installation: {target}") from exc
    if actual != expected:
        raise InstallError(f"target root changed during installation: {target}")


def _walk_target_parts(
    target: Path, rel: Path, expected_identity: tuple[int, int] | None = None
) -> None:
    """Reject any existing symlink/non-directory ancestor without following it."""
    if expected_identity is not None:
        assert_target_identity(target, expected_identity)
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
    if expected_identity is not None:
        assert_target_identity(target, expected_identity)


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
    previous_owned_identities: set[str] | None = None,
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
        merge_module.merge_settings_json(candidate, source, previous_owned_identities)
    else:  # pragma: no cover - guarded by caller
        raise InstallError(f"no semantic merge strategy for {rel}")
    return candidate.read_bytes()


def build_plan(
    scratch: Path,
    target: Path,
    manifest: dict[str, Any],
    preserve_paths: set[str] | None = None,
    expected_identity: tuple[int, int] | None = None,
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
            _walk_target_parts(target, rel_path, expected_identity)

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
                    prior_identities = None
                    if rel == ".claude/settings.json" and isinstance(entry, dict):
                        inventory = entry.get("owned_hook_identities")
                        if isinstance(inventory, list) and all(isinstance(x, str) for x in inventory):
                            prior_identities = set(inventory)
                    content = merged_content(
                        merge_module, rel, destination, source, workspace, prior_identities
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
                    previous_mode=previous_mode,
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
                file_entry["owned_hook_identities"] = settings_hook_identities(item.source)
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


@contextlib.contextmanager
def install_lock(target: Path):
    """Serialize planners/appliers for one canonical target without touching it."""
    digest = hashlib.sha256(str(target).encode()).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"orions-belt-install-{digest}.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallError(f"another install is already running for target: {target}") from exc
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def pinned_target(target: Path):
    """Anchor all target I/O to an open Linux directory descriptor."""
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != target_identity(target):
            raise InstallError(f"target root changed while being pinned: {target}")
        anchored = Path(f"/proc/self/fd/{fd}")
        if not anchored.is_dir():
            raise InstallError("/proc/self/fd is required to anchor target writes on this platform")
        yield anchored
    finally:
        os.close(fd)


def _remove_empty_parents(path: Path, target: Path) -> None:
    """Remove only empty directories created by this apply, never user data."""
    current = path
    while current != target:
        try:
            current.rmdir()
        except (FileNotFoundError, OSError):
            return
        current = current.parent


def recover(target: Path, expected_identity: tuple[int, int] | None = None) -> bool:
    if expected_identity is not None:
        assert_target_identity(target, expected_identity)
    journal_path = _journal_path(target)
    if not journal_path.exists():
        return False
    _walk_target_parts(target, JOURNAL_REL, expected_identity)
    journal = load_json(journal_path, "install journal")
    if journal.get("version") != JOURNAL_VERSION:
        raise InstallError(f"unsupported install journal schema: {journal_path}")
    backup_raw = journal.get("backup_root")
    if not isinstance(backup_raw, str):
        raise InstallError(f"journal backup_root must be a string: {journal_path}")
    backup_rel = validate_rel(backup_raw)
    backup_root = target / backup_rel
    run_id = backup_root.name
    expected = target / BACKUP_ROOT_REL / run_id
    if (
        backup_rel.parent != BACKUP_ROOT_REL
        or not RUN_ID_RE.fullmatch(run_id)
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
    if backup_root_resolved != expected.resolve(strict=True):
        raise InstallError(f"journal backup directory does not resolve exactly as managed: {backup_root}")

    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise InstallError(f"install journal has invalid entries: {journal_path}")
    seen_entries: set[str] = set()
    created_dirs = journal.get("created_dirs", [])
    if not isinstance(created_dirs, list) or not all(isinstance(item, str) for item in created_dirs):
        raise InstallError(f"install journal has invalid created_dirs: {journal_path}")
    for raw in created_dirs:
        validate_rel(raw)

    validated: list[tuple[dict[str, Any], Path, Path | None, int, int]] = []
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
            before_mode = int(str(entry.get("before_mode", "")), 8)
            after_mode = int(str(entry.get("after_mode", "")), 8)
        except ValueError as exc:
            raise InstallError(f"install journal has an invalid mode for {rel_string}") from exc
        before_hash = entry.get("before_sha256")
        after_hash = entry.get("after_sha256")
        if (before_hash is not None and not isinstance(before_hash, str)) or not isinstance(after_hash, str):
            raise InstallError(f"install journal has invalid hashes for {rel_string}")
        if bool(entry["existed"]) != (before_hash is not None):
            raise InstallError(f"install journal has inconsistent prior state for {rel_string}")
        backup: Path | None = None
        if entry["existed"]:
            backup = backup_root / rel
            _walk_target_parts(backup_root, rel)
            if not backup.is_file() or backup.is_symlink():
                raise InstallError(f"journal backup is missing or unsafe: {backup}")
            if sha256_file(backup) != before_hash:
                raise InstallError(f"journal backup hash mismatch: {backup}")
        validated.append((entry, target / rel, backup, before_mode, after_mode))
        seen_entries.add(rel_string)

    # Validate every destination before restoring any of them. A file may be
    # either at its pre-transaction state (not written yet) or at the exact
    # state this transaction intended. Anything else is a post-crash edit and
    # must survive for manual reconciliation.
    states: list[str] = []
    for entry, destination, _backup, before_mode, after_mode in validated:
        rel = validate_rel(str(entry["path"]))
        _walk_target_parts(target, rel, expected_identity)
        if not destination.exists():
            state = "before" if not entry["existed"] else "missing"
        else:
            current_hash = sha256_file(destination)
            current_mode = stat.S_IMODE(destination.stat().st_mode)
            if entry["existed"] and current_hash == entry["before_sha256"] and current_mode == before_mode:
                state = "before"
            elif current_hash == entry["after_sha256"] and current_mode == after_mode:
                state = "after"
            else:
                state = "conflict"
        if state in {"missing", "conflict"}:
            raise InstallError(
                "recovery conflict; target changed after the interrupted apply: "
                f"{destination}"
            )
        states.append(state)

    for (entry, destination, backup, before_mode, _after_mode), state in reversed(list(zip(validated, states))):
        if state == "before":
            continue
        if entry["existed"]:
            assert backup is not None
            atomic_write(destination, backup.read_bytes(), before_mode)
        else:
            destination.unlink()

    # Commit recovery by removing the journal first. A crash after this point
    # can leave only an inert backup directory; the inverse order can leave an
    # unrecoverable live journal whose backup has vanished.
    journal_path.unlink(missing_ok=True)
    shutil.rmtree(backup_root, ignore_errors=True)
    for raw in sorted(created_dirs, key=lambda item: len(Path(item).parts), reverse=True):
        rel_dir = validate_rel(raw)
        directory = target / rel_dir
        try:
            directory.rmdir()
        except (FileNotFoundError, OSError):
            pass
    _remove_empty_parents(backup_root.parent, target)
    _remove_empty_parents(journal_path.parent, target)
    return True


def apply_plan(
    plan: list[PlannedFile],
    target: Path,
    manifest: dict[str, Any],
    fail_after: int | None = None,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    if expected_identity is None:
        expected_identity = target_identity(target)
    assert_target_identity(target, expected_identity)

    # Revalidate the exact plan snapshot before creating backup infrastructure.
    # The journal must never silently adopt an edit made between planning and apply.
    for item in plan:
        _walk_target_parts(target, validate_rel(item.rel), expected_identity)
        current_exists = item.destination.exists()
        current_hash = sha256_file(item.destination) if current_exists else None
        current_mode = stat.S_IMODE(item.destination.stat().st_mode) if current_exists else None
        if (
            current_exists != item.previous_exists
            or current_hash != item.previous_hash
            or current_mode != item.previous_mode
        ):
            raise InstallError(f"target changed after planning and before backup: {item.destination}")

    created_dirs: set[str] = set()
    for destination in [item.destination for item in plan] + [target / MANIFEST_REL, target / JOURNAL_REL]:
        parent = destination.parent
        while parent != target:
            if not parent.exists():
                created_dirs.add(parent.relative_to(target).as_posix())
            parent = parent.parent
    run_id = uuid.uuid4().hex
    backup_root = target / BACKUP_ROOT_REL / run_id
    backup_root.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []

    manifest_path = target / MANIFEST_REL
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    all_backups: list[tuple[str, Path, bool, int, bytes, int]] = []
    for item in plan:
        if item.action in {"unchanged", "preserve"}:
            continue
        old_mode = stat.S_IMODE(item.destination.stat().st_mode) if item.previous_exists else item.mode
        all_backups.append((item.rel, item.destination, item.previous_exists, old_mode, item.content, item.mode))
    manifest_exists = manifest_path.exists()
    manifest_old_mode = stat.S_IMODE(manifest_path.stat().st_mode) if manifest_exists else 0o644
    all_backups.append(
        (MANIFEST_REL.as_posix(), manifest_path, manifest_exists, manifest_old_mode, manifest_bytes, 0o644)
    )

    before_states: dict[str, tuple[bool, str | None, int]] = {}
    try:
        for rel, destination, existed, old_mode, after_content, after_mode in all_backups:
            before_hash = sha256_file(destination) if existed else None
            before_states[rel] = (existed, before_hash, old_mode)
            if existed:
                backup = backup_root / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            entries.append({
                "path": rel,
                "existed": existed,
                "before_sha256": before_hash,
                "before_mode": oct(old_mode),
                "after_sha256": sha256_bytes(after_content),
                "after_mode": oct(after_mode),
            })

        journal = {
            "version": JOURNAL_VERSION,
            "backup_root": (BACKUP_ROOT_REL / run_id).as_posix(),
            "entries": entries,
            "created_dirs": sorted(created_dirs),
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
            _walk_target_parts(target, validate_rel(item.rel), expected_identity)
            existed, expected_hash, expected_mode = before_states[item.rel]
            current_exists = item.destination.exists()
            if current_exists != existed or (
                current_exists
                and (
                    sha256_file(item.destination) != expected_hash
                    or stat.S_IMODE(item.destination.stat().st_mode) != expected_mode
                )
            ):
                raise InstallError(f"target changed after planning and before apply: {item.destination}")
            atomic_write(item.destination, item.content, item.mode)
            writes += 1
            if fail_after is not None and writes >= fail_after:
                raise InstallError(f"injected failure after {writes} writes")

        manifest_existed, manifest_hash, manifest_mode = before_states[MANIFEST_REL.as_posix()]
        current_manifest_exists = manifest_path.exists()
        if current_manifest_exists != manifest_existed or (
            current_manifest_exists
            and (
                sha256_file(manifest_path) != manifest_hash
                or stat.S_IMODE(manifest_path.stat().st_mode) != manifest_mode
            )
        ):
            raise InstallError(f"ownership manifest changed after planning: {manifest_path}")
        atomic_write(manifest_path, manifest_bytes)
    except BaseException:
        recover(target, expected_identity)
        raise
    else:
        # Journal removal is the commit point; an orphaned backup is safe.
        _journal_path(target).unlink(missing_ok=True)
        shutil.rmtree(backup_root, ignore_errors=True)


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
        display_target = target

        if args.plan_json:
            plan_output = args.plan_json.absolute()
            resolved_plan_output = plan_output.resolve(strict=False)
            try:
                resolved_plan_output.relative_to(display_target)
            except ValueError:
                pass
            else:
                raise InstallError(
                    "--plan-json must be outside the target so dry-run cannot mutate it: "
                    f"{plan_output} -> {resolved_plan_output}"
                )

        display_identity = target_identity(display_target)
        with install_lock(display_target), pinned_target(display_target) as target:
            expected_identity = target_identity(target)
            if _journal_path(target).exists() and args.dry_run:
                raise InstallError(
                    "incomplete journal requires a non-dry-run invocation for safe recovery"
                )
            if recover(target, expected_identity):
                print("install_apply: recovered an incomplete previous apply", file=sys.stderr)

            manifest = load_manifest(target)
            preserve_paths = {validate_rel(raw).as_posix() for raw in args.preserve}
            rendered_paths = {
                validate_rel(path.relative_to(scratch).as_posix()).as_posix()
                for path in source_files(scratch)
            }
            missing_preserves = sorted(preserve_paths - rendered_paths)
            if missing_preserves:
                raise InstallError(
                    "--preserve path is not present in this render: " + ", ".join(missing_preserves)
                )
            plan = build_plan(scratch, target, manifest, preserve_paths, expected_identity)
            assert_target_identity(target, expected_identity)
            public_plan = plan_document(plan, display_target)
            encoded_plan = json.dumps(public_plan, indent=2, ensure_ascii=False) + "\n"
            if args.plan_json:
                plan_output.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(plan_output, encoded_plan.encode())
            print(encoded_plan, end="")
            if not args.dry_run:
                next_manifest = manifest_for(plan, manifest, parse_metadata(args.metadata_json))
                injected = os.environ.get("ORIONS_BELT_FAIL_AFTER")
                apply_plan(
                    plan, target, next_manifest, int(injected) if injected else None,
                    expected_identity,
                )
            assert_target_identity(display_target, display_identity)
        return 0
    except (InstallError, OSError, ValueError) as exc:
        print(f"install_apply: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
