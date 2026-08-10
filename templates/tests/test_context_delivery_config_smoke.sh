#!/usr/bin/env bash
set -uo pipefail
missing=0
checked=0
check() {
  local name="$1"; shift
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "SKIP: $name is not installed"
    missing=$((missing+1)); return 0
  fi
  checked=$((checked+1))
  echo "== $name =="
  "$@" || { echo "FAIL: $*" >&2; exit 1; }
}
check claude claude --version
if command -v claude >/dev/null 2>&1; then claude --help >/dev/null || exit 1; fi
check codex codex --version
if command -v codex >/dev/null 2>&1; then codex exec --help >/dev/null || exit 1; codex features list >/dev/null || exit 1; fi
check codegraph codegraph --version
if command -v codegraph >/dev/null 2>&1; then codegraph serve --help >/dev/null || exit 1; fi
if [ "$checked" -eq 0 ]; then exit 77; fi
if [ "$missing" -gt 0 ]; then echo "PARTIAL: $missing optional/required runtime CLIs absent"; exit 77; fi
echo context-delivery-config-smoke-ok
