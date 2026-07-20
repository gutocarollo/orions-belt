#!/usr/bin/env bash
# set_hooks_path.sh — activates core.hooksPath=.githooks WITHOUT clobbering
# (A2, a real gap from the post-v1.0.0 adversarial review: the `_task` in
# copier.yml ran `git config core.hooksPath .githooks` UNCONDITIONALLY — in a
# brownfield project with Husky (or any other already-configured hooksPath)
# that silently disabled the user's hook manager).
#
# Single source: called both by the `_task` in copier.yml (runs inside the dst
# at the end of `copier copy`/`update`, cwd = root of the rendered project) and
# by `harness-install.sh` (calls it explicitly against the TARGET after the
# merge, because in brownfield the `_task` runs only inside the SCRATCH — see
# the comment at the top of harness-install.sh).
#
# Usage: set_hooks_path.sh [target-dir] [--chain-existing]   (default: cwd)
# A detected manager is never displaced. Chaining is explicit and currently
# implemented only for Husky, where the target hook can be updated safely with
# an idempotent marked block.
set -uo pipefail

TARGET="${1:-.}"
CHAIN_EXISTING=0
[ "${2:-}" = "--chain-existing" ] && CHAIN_EXISTING=1
cd "$TARGET" 2>/dev/null || { echo "orions-belt: set_hooks_path.sh: directory '$TARGET' does not exist -- nothing to do" >&2; exit 0; }
TARGET="$(pwd -P)"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "orions-belt: '$TARGET' is not a git repo yet -- run 'git init && git config core.hooksPath .githooks' manually to activate the ref-integrity pre-commit" >&2
  exit 0
fi

CURRENT_HP="$(git config --get core.hooksPath 2>/dev/null || true)"
HUSKY_HOOK="$TARGET/.husky/pre-commit"
HUSKY_DETECTED=0
if [ -e "$HUSKY_HOOK" ] || [ -L "$HUSKY_HOOK" ] || [ -L "$TARGET/.husky" ]; then
  if [ -L "$TARGET/.husky" ] || [ ! -d "$TARGET/.husky" ]; then
    echo "orions-belt: unsafe Husky directory (symlink or non-directory): $TARGET/.husky" >&2
    exit 1
  fi
  if [ -L "$HUSKY_HOOK" ] || [ ! -f "$HUSKY_HOOK" ]; then
    echo "orions-belt: unsafe Husky pre-commit (symlink or non-regular file): $HUSKY_HOOK" >&2
    exit 1
  fi
  HUSKY_REAL="$(realpath -e -- "$HUSKY_HOOK" 2>/dev/null || true)"
  case "$HUSKY_REAL" in
    "$TARGET"/*) HUSKY_DETECTED=1 ;;
    *) echo "orions-belt: Husky pre-commit resolves outside the project: $HUSKY_HOOK" >&2; exit 1 ;;
  esac
fi

chain_husky() {
  if grep -q '^# orions-belt:begin pre-commit$' "$HUSKY_HOOK" 2>/dev/null; then
    if [ "$(grep -c '^# orions-belt:begin pre-commit$' "$HUSKY_HOOK")" -eq 1 ] \
      && [ "$(grep -c '^# orions-belt:end pre-commit$' "$HUSKY_HOOK")" -eq 1 ] \
      && grep -Fqx 'ORIONS_BELT_ROOT="$(git rev-parse --show-toplevel)"' "$HUSKY_HOOK" \
      && grep -Fqx 'export ORIONS_BELT_ROOT' "$HUSKY_HOOK" \
      && grep -Fqx 'bash "$ORIONS_BELT_ROOT/.githooks/pre-commit" || exit $?' "$HUSKY_HOOK"; then
      echo "orions-belt: Husky pre-commit is already chained (idempotent)"
      return 0
    fi
    echo "orions-belt: incomplete or modified orions-belt block in Husky pre-commit; refusing false-success reconciliation: $HUSKY_HOOK" >&2
    return 1
  fi
  if grep -q '^# orions-belt:end pre-commit$' "$HUSKY_HOOK" 2>/dev/null; then
    echo "orions-belt: orphaned orions-belt end marker in Husky pre-commit: $HUSKY_HOOK" >&2
    return 1
  fi
  [ -w "$HUSKY_HOOK" ] || { echo "orions-belt: cannot chain non-writable Husky hook: $HUSKY_HOOK" >&2; return 1; }
  local temp_hook
  temp_hook="$(mktemp "$TARGET/.husky/.pre-commit.orions-belt.XXXXXX")" || return 1
  if ! {
    IFS= read -r first_line || first_line=""
    if [[ "$first_line" == '#!'* ]]; then
      printf '%s\n' "$first_line"
    fi
    # Chain before any user `exit`, `exec`, or failing command. Appending the
    # block is not an execution guarantee for arbitrary existing hooks.
    printf '%s\n%s\n%s\n%s\n%s\n' \
      '# orions-belt:begin pre-commit' \
      'ORIONS_BELT_ROOT="$(git rev-parse --show-toplevel)"' \
      'export ORIONS_BELT_ROOT' \
      'bash "$ORIONS_BELT_ROOT/.githooks/pre-commit" || exit $?' \
      '# orions-belt:end pre-commit'
    if [ -n "$first_line" ] && [[ "$first_line" != '#!'* ]]; then
      printf '%s\n' "$first_line"
    fi
    cat
  } < "$HUSKY_HOOK" > "$temp_hook"; then
    rm -f -- "$temp_hook"
    return 1
  fi
  chmod --reference="$HUSKY_HOOK" "$temp_hook" || { rm -f -- "$temp_hook"; return 1; }
  mv -f -- "$temp_hook" "$HUSKY_HOOK" || { rm -f -- "$temp_hook"; return 1; }
  echo "orions-belt: chained .githooks/pre-commit into .husky/pre-commit"
}

if [ -z "$CURRENT_HP" ]; then
  if [ "$HUSKY_DETECTED" -eq 1 ]; then
    if [ "$CHAIN_EXISTING" -eq 1 ]; then
      chain_husky || exit 1
    else
      echo "orions-belt: Husky detected at .husky/pre-commit while core.hooksPath is empty -- .githooks was NOT activated, because a later 'husky' prepare would replace it. Re-run with --chain-hooks to add the explicit idempotent chain." >&2
    fi
  elif git config core.hooksPath .githooks; then
    echo "orions-belt: core.hooksPath -> .githooks"
  else
    echo "orions-belt: failed to set core.hooksPath=.githooks" >&2
    exit 1
  fi
elif [ "$CURRENT_HP" = ".githooks" ]; then
  echo "orions-belt: core.hooksPath is already .githooks (idempotent, nothing to do)"
elif [ "$HUSKY_DETECTED" -eq 1 ] && { [ "$CURRENT_HP" = ".husky" ] || [ "$CURRENT_HP" = ".husky/_" ]; }; then
  if [ "$CHAIN_EXISTING" -eq 1 ]; then
    chain_husky || exit 1
  else
    echo "orions-belt: Husky owns core.hooksPath='$CURRENT_HP' -- NOT overwritten. Re-run with --chain-hooks to add the explicit idempotent chain." >&2
  fi
else
  # GATE A2: never overwrite an already-customized hooksPath (Husky, lefthook,
  # husky.sh, any other manager). Warn and teach the compatible chaining
  # instead of a silent clobber.
  echo "orions-belt: core.hooksPath already points to '$CURRENT_HP' (e.g. Husky/another hook manager) -- NOT overwritten (A2, anti-clobber). To activate the harness ref-integrity without replacing your hook manager, chain it manually: append to the end of your hook at '$CURRENT_HP/pre-commit' a call to this project's 'bash \"\$(git rev-parse --show-toplevel)/.githooks/pre-commit\"'. If you prefer to replace it entirely instead of chaining, run 'git config core.hooksPath .githooks' yourself. See docs/manual/14-instalacao-e-update.md." >&2
fi

exit 0
