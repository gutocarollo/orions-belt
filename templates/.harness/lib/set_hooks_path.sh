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
# Usage: set_hooks_path.sh [target-dir]   (default: cwd)
# Fail-open: never returns != 0 (must never bring down the Copier install/task).
set -uo pipefail

TARGET="${1:-.}"
cd "$TARGET" 2>/dev/null || { echo "orions-belt: set_hooks_path.sh: directory '$TARGET' does not exist -- nothing to do" >&2; exit 0; }

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "orions-belt: '$TARGET' is not a git repo yet -- run 'git init && git config core.hooksPath .githooks' manually to activate the ref-integrity pre-commit" >&2
  exit 0
fi

CURRENT_HP="$(git config --get core.hooksPath 2>/dev/null || true)"

if [ -z "$CURRENT_HP" ]; then
  git config core.hooksPath .githooks
  echo "orions-belt: core.hooksPath -> .githooks"
elif [ "$CURRENT_HP" = ".githooks" ]; then
  echo "orions-belt: core.hooksPath is already .githooks (idempotent, nothing to do)"
else
  # GATE A2: never overwrite an already-customized hooksPath (Husky, lefthook,
  # husky.sh, any other manager). Warn and teach the compatible chaining
  # instead of a silent clobber.
  echo "orions-belt: core.hooksPath already points to '$CURRENT_HP' (e.g. Husky/another hook manager) -- NOT overwritten (A2, anti-clobber). To activate the harness ref-integrity without replacing your hook manager, chain it manually: append to the end of your hook at '$CURRENT_HP/pre-commit' a call to this project's 'bash \"\$(git rev-parse --show-toplevel)/.githooks/pre-commit\"'. If you prefer to replace it entirely instead of chaining, run 'git config core.hooksPath .githooks' yourself. See docs/manual/14-instalacao-e-update.md." >&2
fi

exit 0
