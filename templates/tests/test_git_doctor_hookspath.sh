#!/usr/bin/env bash
# test_git_doctor_hookspath.sh — regression for the "inert githook" upstream
# defect found while manually porting hooks into
# WhatsApp_Agent_Chat_slim-shape (2026-07-27): .githooks/pre-commit is
# unconditionally materialized by the installer, but core.hooksPath activation
# can be skipped (Husky/pre-commit framework anti-clobber, A2) or simply never
# run (brownfield manual port), and nothing after install time re-checks it --
# the gate can sit silently dead indefinitely. git-doctor.sh.jinja (SessionStart,
# every session) now re-diagnoses this on every run instead of only warning
# once during `copier copy`.
#
# Runs git-doctor.sh.jinja directly (no copier render needed: the new check
# does not touch any Jinja variable) against throwaway git repos, driving ROOT
# via CLAUDE_PROJECT_DIR so cwd is irrelevant.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
GD="$REPO_ROOT/templates/.harness/hooks/git-doctor.sh.jinja"
FAIL=0
assert() { if eval "$2"; then echo "PASS: $1"; else echo "FAIL: $1"; FAIL=1; fi; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/gd-hookspath.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

run_doctor() { CLAUDE_PROJECT_DIR="$1" bash "$GD" 2>&1; }

# --- Case 1: no .githooks/pre-commit at all (not installed) -> silent ---
NONE="$WORK/none"; mkdir -p "$NONE"; git -C "$NONE" init -q
OUT="$(run_doctor "$NONE")"
assert "not installed: no INERT alert" \
  '! printf "%s" "$OUT" | grep -q "INERT"'

# --- Case 2: materialized, core.hooksPath unset, no chain -> INERT alert ---
INERT="$WORK/inert"; mkdir -p "$INERT/.githooks"; git -C "$INERT" init -q
printf '#!/usr/bin/env bash\nexit 0\n' > "$INERT/.githooks/pre-commit"
chmod +x "$INERT/.githooks/pre-commit"
OUT="$(run_doctor "$INERT")"
assert "unset hooksPath, no chain: INERT alert fires" \
  'printf "%s" "$OUT" | grep -q "INERT"'
assert "INERT alert names the empty hooksPath" \
  'printf "%s" "$OUT" | grep -qF "core.hooksPath='"'"'<empty>'"'"'"'

# --- Case 3: activated correctly -> silent ---
ACTIVE="$WORK/active"; mkdir -p "$ACTIVE/.githooks"; git -C "$ACTIVE" init -q
printf '#!/usr/bin/env bash\nexit 0\n' > "$ACTIVE/.githooks/pre-commit"
chmod +x "$ACTIVE/.githooks/pre-commit"
git -C "$ACTIVE" config core.hooksPath .githooks
OUT="$(run_doctor "$ACTIVE")"
assert "core.hooksPath=.githooks: no INERT alert" \
  '! printf "%s" "$OUT" | grep -q "INERT"'

# --- Case 4: Husky owns hooksPath but chained the harness hook in -> silent ---
HUSKY="$WORK/husky"; mkdir -p "$HUSKY/.githooks" "$HUSKY/.husky"; git -C "$HUSKY" init -q
printf '#!/usr/bin/env bash\nexit 0\n' > "$HUSKY/.githooks/pre-commit"
chmod +x "$HUSKY/.githooks/pre-commit"
git -C "$HUSKY" config core.hooksPath .husky
cat > "$HUSKY/.husky/pre-commit" <<'EOF'
#!/usr/bin/env sh
# orions-belt:begin pre-commit
ORIONS_BELT_ROOT="$(git rev-parse --show-toplevel)"
export ORIONS_BELT_ROOT
bash "$ORIONS_BELT_ROOT/.githooks/pre-commit" || exit $?
# orions-belt:end pre-commit
EOF
OUT="$(run_doctor "$HUSKY")"
assert "Husky chained: no INERT alert" \
  '! printf "%s" "$OUT" | grep -q "INERT"'

# --- Case 5: pre-commit framework chained via .pre-commit-config.yaml -> silent ---
PC="$WORK/precommit"; mkdir -p "$PC/.githooks"; git -C "$PC" init -q
printf '#!/usr/bin/env bash\nexit 0\n' > "$PC/.githooks/pre-commit"
chmod +x "$PC/.githooks/pre-commit"
cat > "$PC/.pre-commit-config.yaml" <<'EOF'
repos:
  - repo: local
    hooks:
      - id: orions-belt
        name: orions-belt ref-integrity
        entry: bash .githooks/pre-commit
        language: system
        always_run: true
EOF
OUT="$(run_doctor "$PC")"
assert "pre-commit framework chained: no INERT alert" \
  '! printf "%s" "$OUT" | grep -q "INERT"'

# --- Case 6: pre-commit framework present but NOT chained -> INERT alert ---
PCU="$WORK/precommit-unchained"; mkdir -p "$PCU/.githooks"; git -C "$PCU" init -q
printf '#!/usr/bin/env bash\nexit 0\n' > "$PCU/.githooks/pre-commit"
chmod +x "$PCU/.githooks/pre-commit"
printf 'repos: []\n' > "$PCU/.pre-commit-config.yaml"
OUT="$(run_doctor "$PCU")"
assert "pre-commit framework present but unchained: INERT alert fires" \
  'printf "%s" "$OUT" | grep -q "INERT"'

echo
if [ "$FAIL" -eq 0 ]; then echo "RESULT: git-doctor inert-hookspath detection PASSED"; else echo "RESULT: FAILURES"; fi
exit "$FAIL"
