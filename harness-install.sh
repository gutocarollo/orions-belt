#!/usr/bin/env bash
# harness-install.sh — BROWNFIELD-SAFE bootstrap for installing/updating
# orions-belt into a target project (B3, BLOCKING gap from the post-v1.0.0
# adversarial review).
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
# from a previous `copier copy` of the SAME template (it needs an existing
# `.harness/answers.yml` and a coherent history) — it is not meant to "adopt"
# a repo that already had a life of its own before the harness. That is why
# this bootstrap exists as a 3rd path, specific to the FIRST brownfield
# adoption (subsequent updates use `copier update` normally — see
# docs/manual/14-instalacao-e-update.md).
#
# THE FLOW (never writes to the target project via a direct `copier copy`):
#   1. Renders the ENTIRE framework into a temporary SCRATCH directory via
#      `copier copy` (this repo's root — never the target project).
#   2. Applies it to the target project, file by file:
#        - does not exist in the target      -> copy directly.
#        - is one of the 4 SENSITIVE files (AGENTS.md, .claude/CLAUDE.md,
#          .claude/settings.json, .gitignore) AND already exists in the target
#          -> ADDITIVE merge via `.harness/lib/merge_docs.py` (the binary
#          RENDERED in scratch — the correct version of the tag/HEAD being
#          installed, not the one from this script's local checkout).
#        - any other framework-owned file that already exists (reinstall
#          /manual update) -> direct overwrite (it is harness-owned, not
#          user-owned; see Known gap in the harness-init skill).
#   3. `.harness/answers.yml` reaches the target project via step 2 (it is
#      just one more "file that does not exist" on the 1st install) — a
#      prerequisite for `copier update --answers-file .harness/answers.yml`
#      in the future.
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
#   ./harness-install.sh <target-dir> [-- ] [copier copy args...]
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
usage: harness-install.sh <target-dir> [copier copy args...]

Installs/adopts orions-belt into a target project (greenfield OR brownfield)
without overwriting pre-existing AGENTS.md / .claude/CLAUDE.md /
.claude/settings.json / .gitignore and without clobbering an already-customized
core.hooksPath. See the comment at the top of this file for the full flow (B3).

examples:
  ./harness-install.sh ../my-project \
    --data project_name=my-project --data owner_name=Someone --defaults
  ./harness-install.sh ../my-project --vcs-ref v1.0.0 \
    --data project_name=my-project --data owner_name=Someone --defaults

'--trust' is added automatically. Other args are forwarded verbatim to
'copier copy' (--data, --vcs-ref, --defaults, etc.).
EOF
}

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage >&2
  exit 1
fi

TARGET_ARG="$1"; shift
COPIER_ARGS=("$@")

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$HERE"

if ! command -v uvx >/dev/null 2>&1; then
  echo "harness-install.sh: 'uvx' not found on PATH -- install uv (https://docs.astral.sh/uv/) to run copier." >&2
  exit 1
fi

# M3/H4 (adversarial review): PLATFORM preflight -- "portable" was not
# declared anywhere, and the hooks/scripts (.harness/hooks|lib/) require
# Bash>=4 + GNU coreutils + flock + python3 (see check-platform.sh for the
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

mkdir -p "$TARGET_ARG"
TARGET="$(cd "$TARGET_ARG" && pwd)"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/harness-install.XXXXXX")"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

echo "harness-install.sh: rendering $REPO_ROOT -> scratch $SCRATCH ..." >&2
uvx copier copy "$REPO_ROOT" "$SCRATCH" "${COPIER_ARGS[@]}" --trust -q

LIB="$SCRATCH/.harness/lib"
if [ ! -f "$LIB/merge_docs.py" ]; then
  echo "harness-install.sh: render did not produce .harness/lib/merge_docs.py -- broken template or incomplete --data (see stderr above)." >&2
  exit 1
fi

# The 4 SENSITIVE files (B3): may have user content, NEVER a direct overwrite
# if they already exist in the target.
SENSITIVE_PATHS=(
  "AGENTS.md"
  ".claude/CLAUDE.md"
  ".claude/settings.json"
  ".gitignore"
)

is_sensitive() {
  local rel="$1" s
  for s in "${SENSITIVE_PATHS[@]}"; do
    [ "$rel" = "$s" ] && return 0
  done
  return 1
}

N_CREATED=0
N_OVERWRITTEN=0
N_MERGED=0
N_SKIPPED_ESCAPE=0

# Containment root: the canonical absolute path of TARGET. Every write must land
# strictly inside it.
TARGET_REAL="$(cd "$TARGET" 2>/dev/null && pwd -P)" || { echo "harness-install.sh: cannot resolve TARGET '$TARGET'." >&2; exit 1; }

while IFS= read -r -d '' f; do
  rel="${f#"$SCRATCH"/}"
  dest="$TARGET/$rel"

  # Symlink/containment guard (adversarial-audit gap #3): never write THROUGH a
  # symlink or OUTSIDE TARGET. A symlinked dest (or a symlinked parent dir, e.g.
  # a `.codex/` pointing elsewhere) would make `cp`/merge write to an external
  # file. Resolve the real parent; if it escapes TARGET_REAL, skip and warn.
  parent="$(dirname "$dest")"
  mkdir -p "$parent" 2>/dev/null || true
  real_parent="$(cd "$parent" 2>/dev/null && pwd -P)" || real_parent=""
  case "${real_parent:-/nonexistent}/" in
    "$TARGET_REAL"/*|"$TARGET_REAL"/) : ;;  # inside target — ok
    *)
      echo "SKIP (path escapes target via symlink): $rel -> ${real_parent:-unresolved}" >&2
      N_SKIPPED_ESCAPE=$((N_SKIPPED_ESCAPE + 1))
      continue
      ;;
  esac
  # If dest itself is a symlink, drop it so we write a real file inside TARGET
  # (never overwrite whatever it points at). For the 4 sensitive files this also
  # means a symlinked instruction file is replaced, not written through.
  if [ -L "$dest" ]; then
    echo "note: replacing symlink with a real file: $rel" >&2
    rm -f "$dest"
  fi

  if is_sensitive "$rel"; then
    if [ -f "$dest" ]; then
      case "$rel" in
        AGENTS.md|.claude/CLAUDE.md)
          RESULT="$(python3 "$LIB/merge_docs.py" markdown --existing "$dest" --new "$f" --label harness-install)"
          ;;
        .claude/settings.json)
          RESULT="$(python3 "$LIB/merge_docs.py" settings-json --existing "$dest" --new "$f")"
          ;;
        .gitignore)
          RESULT="$(python3 "$LIB/merge_docs.py" gitignore --existing "$dest" --new "$f" --label harness-install)"
          ;;
      esac
      N_MERGED=$((N_MERGED + 1))
      echo "merge  $rel"
      echo "$RESULT" | sed 's/^/         /'
    else
      mkdir -p "$(dirname "$dest")"
      cp "$f" "$dest"
      N_CREATED=$((N_CREATED + 1))
      echo "create $rel"
    fi
  else
    if [ -f "$dest" ]; then
      N_OVERWRITTEN=$((N_OVERWRITTEN + 1))
    else
      N_CREATED=$((N_CREATED + 1))
    fi
    mkdir -p "$(dirname "$dest")"
    cp "$f" "$dest"
  fi
done < <(find "$SCRATCH" -type f -print0)

# A2: activates core.hooksPath without clobbering, explicitly against the
# TARGET (see the note in the header — the _task in copier.yml does not reach
# the target project in this flow because it ran inside the SCRATCH in step 1).
if [ -f "$LIB/set_hooks_path.sh" ]; then
  bash "$LIB/set_hooks_path.sh" "$TARGET"
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
  if command -v python3 >/dev/null 2>&1 && [ -f "$TARGET/.harness/lib/_tooling_conf.py" ]; then
    DS_WEB_APP_DIR="$(HARNESS_PROJECT_ROOT="$TARGET" python3 "$TARGET/.harness/lib/_tooling_conf.py" get HARNESS_WEB_APP_DIR . 2>/dev/null || echo .)"
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

echo
echo "harness-install.sh: done."
echo "  new files created:                   $N_CREATED"
echo "  framework-owned overwritten:         $N_OVERWRITTEN"
echo "  sensitive files merged (additive):   $N_MERGED"
echo "  skipped (path escaped target):       $N_SKIPPED_ESCAPE"
if [ "$N_OVERWRITTEN" -gt 0 ]; then
  echo "  NOTE: 'overwritten' are paths this render ships; if a same-named file was your own"
  echo "        (not a prior harness install), it was replaced. No ownership manifest yet — review with 'git diff'."
fi
echo "  .harness/answers.yml written to:     $TARGET/.harness/answers.yml (needed for a future 'copier update')"
