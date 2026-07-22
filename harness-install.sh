#!/usr/bin/env bash
# harness-install.sh — fail-closed bootstrap/reconciler for installing or
# updating orions-belt in an existing target project.
#
# THE PROBLEM THIS SOLVES: `copier copy <orions-belt> <target-project>
# --trust` run DIRECTLY against a repo that already exists (the common case —
# you are almost always adopting the harness into a live project, not creating
# one from scratch) is circular and destructive:
#   - without `--overwrite`: any name collision (AGENTS.md, .claude/
#     CLAUDE.md, .claude/settings.json, .gitignore) makes Copier abort with
#     exit 1 and the project is left with a PARTIAL install.
#   - with `--overwrite`: the 4 files above (which almost always already
#     have user content) are OVERWRITTEN entirely.
#   - with `--skip`: none of the harness lands in those 4 files — a lame
#     install (settings.json without the harness hooks, for example).
# `copier update` does NOT solve this: it assumes the target project was BORN
# from a previous `copier copy` of the SAME template and cannot see local-only
# brownfield content. This installer is therefore the supported path for both
# first adoption and subsequent brownfield updates.
#
# THE FLOW (never writes to the target project via a direct `copier copy`):
#   1. Renders the ENTIRE framework into a temporary SCRATCH directory via
#      `copier copy` (this repo's root — never the target project).
#   2. Plans every target path before writing. Unknown collisions, symlinks,
#      escapes and locally-modified managed files are fatal. The four shared
#      surfaces use additive/semantic merge; whole-file paths require an
#      ownership hash in `.harness/install-manifest.json`.
#   3. Applies with per-file atomic replace and a rollback journal. This is a
#      recoverable multi-file apply, not a filesystem-wide atomicity claim.
#   4. Activates `core.hooksPath` (A2) by calling `.harness/lib/set_hooks_path.sh`
#      EXPLICITLY against the TARGET. The equivalent `_task` in copier.yml
#      runs inside the SCRATCH in this flow (cwd = scratch during the `copier
#      copy` of step 1, which is not even a git repo) — it does not configure
#      anything in the target project on its own, which is why step 4 is
#      needed here. The script never overwrites an already-customized hooksPath
#      (Husky/lefthook/etc.) — same single source used by `_task`, see the
#      comment in set_hooks_path.sh.
#
# Usage:
#   ./harness-install.sh <target-dir> [installer options] [--] [copier args...]
#
# Examples:
#   ./harness-install.sh ../my-project \
#     --data project_name=my-project --data owner_name=Someone --defaults
#   ./harness-install.sh ../my-project --vcs-ref v1.0.0 \
#     --data project_name=my-project --data owner_name=Someone --defaults
#
# `--trust` is always added by this script (same requirement as any
# `copier copy`/`update` in this repo — see README.md). Extra args are
# forwarded verbatim to `copier copy` (e.g. `--data`, `--vcs-ref`,
# `--defaults`).
set -euo pipefail

usage() {
  cat <<'EOF'
usage: harness-install.sh <target-dir> [installer options] [--] [copier copy args...]

Installs/adopts orions-belt into a target project using a fail-closed plan,
ownership hashes, semantic merges and a rollback journal.

installer options:
  --dry-run          render and print/write the plan without changing target
  --plan-json PATH   persist the machine-readable plan at PATH
  --preserve PATH    explicitly preserve one existing unowned/modified path
                     (repeatable; exact project-relative path, no glob)
  --chain-hooks      explicitly chain .githooks/pre-commit into Husky

examples:
  ./harness-install.sh ../my-project \
    --data project_name=my-project --data owner_name=Someone --defaults
  ./harness-install.sh ../my-project --vcs-ref v1.0.0 \
    --data project_name=my-project --data owner_name=Someone --defaults

'--trust' is added automatically. Arguments after '--' and unrecognized
options are forwarded to 'copier copy' (--data, --vcs-ref, --defaults, etc.).
EOF
}

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage >&2
  exit 1
fi

TARGET_ARG="$1"; shift
COPIER_ARGS=()
INSTALL_DRY_RUN=0
INSTALL_PLAN_JSON=""
CHAIN_HOOKS=0
HAS_DATA_FILE=0
PRESERVE_PATHS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      INSTALL_DRY_RUN=1
      shift
      ;;
    --plan-json)
      [ "$#" -ge 2 ] || { echo "harness-install.sh: --plan-json requires a path" >&2; exit 64; }
      INSTALL_PLAN_JSON="$2"
      shift 2
      ;;
    --chain-hooks)
      CHAIN_HOOKS=1
      shift
      ;;
    --preserve)
      [ "$#" -ge 2 ] || { echo "harness-install.sh: --preserve requires a project-relative path" >&2; exit 64; }
      PRESERVE_PATHS+=("$2")
      shift 2
      ;;
    --data-file)
      [ "$#" -ge 2 ] || { echo "harness-install.sh: --data-file requires a path" >&2; exit 64; }
      HAS_DATA_FILE=1
      COPIER_ARGS+=("$1" "$2")
      shift 2
      ;;
    --data-file=*)
      HAS_DATA_FILE=1
      COPIER_ARGS+=("$1")
      shift
      ;;
    --)
      shift
      COPIER_ARGS+=("$@")
      break
      ;;
    *)
      COPIER_ARGS+=("$1")
      shift
      ;;
  esac
done

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [ -z "$SCRIPT_SOURCE" ] || [ ! -f "$SCRIPT_SOURCE" ]; then
  echo "harness-install.sh: this script must run from a checked-out, version-pinned orions-belt release; piping it to 'bash -s' cannot locate copier.yml." >&2
  exit 64
fi
HERE="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
REPO_ROOT="$HERE"

if ! command -v python3 >/dev/null 2>&1; then
  echo "harness-install.sh: 'python3' not found on PATH; Python 3.14 or newer is required." >&2
  exit 1
fi
PYTHON_BIN="$(command -v python3)"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)'; then
  echo "harness-install.sh: Python 3.14 or newer is required; '$PYTHON_BIN' is $("$PYTHON_BIN" --version 2>&1)." >&2
  echo "harness-install.sh: macOS: brew install python@3.14 and place Homebrew bin before /usr/bin in PATH." >&2
  exit 1
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "harness-install.sh: 'uvx' not found on PATH -- install uv (https://docs.astral.sh/uv/) to run copier." >&2
  exit 1
fi

# M3/H4 (adversarial review): PLATFORM preflight -- "portable" was not
# declared anywhere, and the hooks/scripts (.harness/hooks|lib/) require
# Bash>=4 + GNU coreutils + flock + Python>=3.14 (see check-platform.sh for the
# detail of EACH dependency and its fix command). Runs BEFORE the render to
# warn EARLY, but never blocks `copier copy` itself on its own (that is
# platform-agnostic) -- only the behavior of the hooks after install degrades.
# If check-platform.sh does not exist yet in this checkout (old repo version
# before M3), it proceeds without the preflight (fail-open -- it is not a NEW
# requirement to block old installs).
if [ -f "$REPO_ROOT/templates/.harness/lib/check-platform.sh" ]; then
  echo "harness-install.sh: platform preflight (.harness/lib/check-platform.sh) ..." >&2
  if ! bash "$REPO_ROOT/templates/.harness/lib/check-platform.sh"; then
    echo "harness-install.sh: WARNING -- this environment does not meet all the hooks' required dependencies (see above). The install PROCEEDS, but hooks may fail/become no-ops later -- see docs/manual/15-limitacoes-conhecidas.md." >&2
  fi
  echo >&2
fi

if [ -L "$TARGET_ARG" ]; then
  echo "harness-install.sh: target root is a symlink; refusing to install: $TARGET_ARG" >&2
  exit 2
fi
if [ "$INSTALL_DRY_RUN" -eq 1 ] && [ ! -d "$TARGET_ARG" ]; then
  echo "harness-install.sh: dry-run requires an existing target directory and will not create one: $TARGET_ARG" >&2
  exit 2
fi
mkdir -p -- "$TARGET_ARG"
TARGET="$(cd "$TARGET_ARG" && pwd -P)"
TARGET_REAL="$TARGET"

# On a managed reinstall, existing answers are the baseline and explicit
# --data flags are overrides (Copier's documented precedence).  Without this,
# omitting any prior non-default answer silently resets that capability to the
# template default.  Only trust an answers file whose bytes still match this
# installer's ownership manifest; unknown/tampered brownfield files are not
# consumed before the fail-closed planner gets to reject them.
MANAGED_ANSWERS="$TARGET_REAL/.harness/answers.yml"
MANAGED_MANIFEST="$TARGET_REAL/.harness/install-manifest.json"
if [ "$HAS_DATA_FILE" -eq 0 ] && [ -f "$MANAGED_ANSWERS" ] && [ -f "$MANAGED_MANIFEST" ]; then
  if "$PYTHON_BIN" - "$TARGET_REAL" "$MANAGED_ANSWERS" "$MANAGED_MANIFEST" <<'PY'
import hashlib, json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
answers = pathlib.Path(sys.argv[2])
manifest = pathlib.Path(sys.argv[3])
try:
    if answers.is_symlink() or manifest.is_symlink():
        raise ValueError
    answers_real = answers.resolve(strict=True)
    manifest_real = manifest.resolve(strict=True)
    if os.path.commonpath((str(root), str(answers_real))) != str(root):
        raise ValueError
    if os.path.commonpath((str(root), str(manifest_real))) != str(root):
        raise ValueError
    state = json.loads(manifest.read_text(encoding="utf-8"))
    entry = state.get("files", {}).get(".harness/answers.yml", {})
    digest = hashlib.sha256(answers.read_bytes()).hexdigest()
    if entry.get("strategy") != "owned" or entry.get("last_applied_sha256") != digest:
        raise ValueError
except (OSError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  then
    COPIER_ARGS+=(--data-file "$MANAGED_ANSWERS")
    echo "harness-install.sh: reusing managed answers; explicit --data values take precedence" >&2
  else
    echo "harness-install.sh: existing answers are not proven by the ownership manifest; not loading them before conflict validation" >&2
  fi
fi

# Copier synthesizes a different pseudo-commit for every render from a dirty
# local checkout.  Keeping that volatile value in answers.yml makes an
# otherwise identical reinstall rewrite the file forever.  The reconciler has
# its own provenance contract, so normalize both Copier metadata fields to the
# stable release identity used by the install manifest.
TEMPLATE_REF="$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null || echo unversioned)"
TEMPLATE_SOURCE="$(git -C "$REPO_ROOT" config --get remote.origin.url 2>/dev/null || basename "$REPO_ROOT")"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/harness-install.XXXXXX")"
# WORK holds install-time artifacts (plan JSON, apply stdout) that must NEVER
# live inside SCRATCH: source_files() rglobs SCRATCH as the render, so anything
# dropped there gets enumerated and installed into the target (G1 — a 0-byte
# install-plan.stdout.json was landing as an owned file at the target root).
WORK="$(mktemp -d "${TMPDIR:-/tmp}/harness-install-work.XXXXXX")"
cleanup() { rm -rf "$SCRATCH" "$WORK"; }
trap cleanup EXIT

echo "harness-install.sh: rendering $REPO_ROOT -> scratch $SCRATCH ..." >&2
uvx copier copy "$REPO_ROOT" "$SCRATCH" "${COPIER_ARGS[@]}" \
  --data "project_root=$TARGET_REAL" --trust -q

LIB="$SCRATCH/.harness/lib"
if [ ! -f "$LIB/merge_docs.py" ] || [ ! -f "$LIB/install_apply.py" ]; then
  echo "harness-install.sh: render did not produce the merge/apply engine -- broken template or incomplete --data (see stderr above)." >&2
  exit 1
fi

"$PYTHON_BIN" - "$SCRATCH/.harness/answers.yml" "$TEMPLATE_SOURCE" "$TEMPLATE_REF" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source, ref = sys.argv[2:]

def yaml_scalar(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
seen = set()
for index, line in enumerate(lines):
    for key, value in (("_src_path", source), ("_commit", ref)):
        if line.startswith(key + ":"):
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{key}: {yaml_scalar(value)}{newline}"
            seen.add(key)
if seen != {"_src_path", "_commit"}:
    missing = sorted({"_src_path", "_commit"} - seen)
    raise SystemExit(f"answers metadata missing required fields: {', '.join(missing)}")
path.write_text("".join(lines), encoding="utf-8")
PY

# The rendered engine owns planning, containment, semantic merge and rollback.
# It is loaded FROM SCRATCH so a pinned release always applies its matching
# schema/merge behavior.  The target Git index is deliberately irrelevant.
METADATA_JSON="$("$PYTHON_BIN" - "$TEMPLATE_SOURCE" "$TEMPLATE_REF" <<'PY'
import json, sys
print(json.dumps({"source": sys.argv[1], "ref": sys.argv[2]}))
PY
)"
PLAN_OUT="${INSTALL_PLAN_JSON:-$WORK/install-plan.json}"
APPLY_ARGS=(
  --scratch "$SCRATCH"
  --target "$TARGET_REAL"
  --plan-json "$PLAN_OUT"
  --metadata-json "$METADATA_JSON"
)
[ "$INSTALL_DRY_RUN" -eq 1 ] && APPLY_ARGS+=(--dry-run)
for preserved in "${PRESERVE_PATHS[@]}"; do
  APPLY_ARGS+=(--preserve "$preserved")
done

echo "harness-install.sh: planning ownership/containment for $TARGET_REAL ..." >&2
"$PYTHON_BIN" "$LIB/install_apply.py" "${APPLY_ARGS[@]}" > "$WORK/install-plan.stdout.json"

"$PYTHON_BIN" - "$PLAN_OUT" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
counts = plan.get("counts", {})
print("harness-install.sh: plan " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
PY

if [ "$INSTALL_DRY_RUN" -eq 1 ]; then
  echo "harness-install.sh: dry-run complete; target was not changed."
  echo "  plan: $PLAN_OUT"
  exit 0
fi

# A2: activates core.hooksPath without clobbering, explicitly against the
# TARGET (see the note in the header — the _task in copier.yml does not reach
# the target project in this flow because it ran inside the SCRATCH in step 1).
if [ -f "$LIB/set_hooks_path.sh" ]; then
  if [ "$CHAIN_HOOKS" -eq 1 ]; then
    if ! bash "$LIB/set_hooks_path.sh" "$TARGET" --chain-existing; then
      echo "harness-install.sh: ERROR -- files were installed, but explicit Husky chaining failed; inspect .husky/pre-commit and retry manually." >&2
      exit 1
    fi
  else
    if ! bash "$LIB/set_hooks_path.sh" "$TARGET"; then
      echo "harness-install.sh: WARNING -- files were installed, but core.hooksPath activation failed; run bash .harness/lib/set_hooks_path.sh manually." >&2
    fi
  fi
fi

# H2/A6.2 (post-v1.0.0 adversarial review): ds-gate.sh is a RATCHET —
# `MODE=check` without `.ds-baseline.txt` always runs report-only (never
# fails; see the comment at the top of ds-gate.sh) because there is no number
# to compare against. No prior install step generated that baseline — the gate
# stayed permanently inert in EVERY project installed via harness-install.sh,
# even with `ds-gate-posttool` active (use_ds_gate). Fix: the 1st install
# generates `.ds-baseline.txt` automatically (the target project's CURRENT
# count becomes the ratchet floor — it can only get better from here on).
# Signal that "use_ds_gate was active": the presence of the materialized hook
# `.harness/hooks/ds-gate-posttool.sh` (it is gated by filename via Jinja;
# ds-gate.sh itself is always shipped unconditionally, so it is not a signal on
# its own). Does not run again if the baseline already exists (a reinstall
# /update must not reset a ratchet already in progress) — regenerating is an
# explicit user action: `bash .harness/lib/ds-gate.sh --update-baseline`
# (documented in docs/manual/05-hooks-posttooluse.md).
if [ -f "$TARGET/.harness/hooks/ds-gate-posttool.sh" ] && [ -f "$TARGET/.harness/lib/ds-gate.sh" ]; then
  DS_WEB_APP_DIR="."
  if [ -f "$TARGET/.harness/lib/_tooling_conf.py" ]; then
    DS_WEB_APP_DIR="$(HARNESS_PROJECT_ROOT="$TARGET" "$PYTHON_BIN" "$TARGET/.harness/lib/_tooling_conf.py" get HARNESS_WEB_APP_DIR . 2>/dev/null || echo .)"
  fi
  DS_WEB_APP_DIR="${DS_WEB_APP_DIR%/}"
  [ -z "$DS_WEB_APP_DIR" ] && DS_WEB_APP_DIR="."
  DS_BASELINE_DIR="$TARGET"
  [ "$DS_WEB_APP_DIR" != "." ] && DS_BASELINE_DIR="$TARGET/$DS_WEB_APP_DIR"
  if [ -d "$DS_BASELINE_DIR" ] && [ ! -f "$DS_BASELINE_DIR/.ds-baseline.txt" ]; then
    echo
    echo "harness-install.sh: generating initial ds-gate .ds-baseline.txt (anti-hardcode ratchet)..."
    if HARNESS_PROJECT_ROOT="$TARGET" bash "$TARGET/.harness/lib/ds-gate.sh" --update-baseline >/dev/null; then
      echo "  baseline written to $DS_BASELINE_DIR/.ds-baseline.txt -- commit this file."
    else
      echo "  warning: ds-gate.sh --update-baseline failed (non-blocking) -- run it manually later: bash .harness/lib/ds-gate.sh --update-baseline" >&2
    fi
  fi
fi

# Decision report — the install audit trail (what was installed / skipped & why,
# with applied examples). Part of the process: regenerated on every (re)install
# from the manifest + answers. Non-blocking (the install already succeeded).
REPORT_PATH=""
if [ -f "$TARGET/.harness/lib/install_report.py" ]; then
  if REPORT_PATH="$("$PYTHON_BIN" "$TARGET/.harness/lib/install_report.py" --target "$TARGET" \
      --timestamp "$(date '+%Y-%m-%d %H:%M:%S %Z')" 2>/dev/null)"; then
    :
  else
    echo "harness-install.sh: WARNING -- install report generation failed (non-blocking)." >&2
    REPORT_PATH=""
  fi
fi

echo
echo "harness-install.sh: done."
echo "  ownership state: $TARGET/.harness/install-manifest.json"
echo "  rendered answers: $TARGET/.harness/answers.yml"
[ -n "$REPORT_PATH" ] && echo "  decision report: $REPORT_PATH"
echo "  update policy: rerun the installer from a pinned newer release; do not use raw Copier update for brownfield/local-only surfaces"
