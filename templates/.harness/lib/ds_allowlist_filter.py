#!/usr/bin/env python3
"""ds_allowlist_filter — real glob (fnmatch) for the ds-gate.sh allowlist.

Reads `path:lineno:content` lines (output of `grep -rEn`) from stdin and
writes to stdout only the ones that do NOT match any pattern passed in argv.
A separate .py file (instead of `python3 - <<HEREDOC`) is INTENTIONAL:
`python3 -` reads the PROGRAM ITSELF from stdin — a heredoc attached to that
invocation consumes stdin to load the source and the running program's
`sys.stdin` arrives empty, silently discarding the ENTIRE pipe input (real
bug found and fixed this round, H2/A6.3 — confirmed with
`printf 'a\\nb\\n' | python3 - <<'EOF' ... EOF` → `sys.stdin.readlines()`
returns `[]`). A real file script has no such conflict: argv carries the
patterns, stdin is free for the grep pipe.

Usage: grep -rEn ... | python3 ds_allowlist_filter.py '<glob1>' '<glob2>' ...
"""
import fnmatch
import sys


def main() -> int:
    patterns = sys.argv[1:]
    if not patterns:
        sys.stdout.write(sys.stdin.read())
        return 0
    for line in sys.stdin:
        path = line.split(':', 1)[0]
        if path.startswith('./'):
            path = path[2:]
        if any(fnmatch.fnmatch(path, pat) for pat in patterns):
            continue
        sys.stdout.write(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
