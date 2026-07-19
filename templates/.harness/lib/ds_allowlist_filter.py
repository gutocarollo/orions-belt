#!/usr/bin/env python3
"""ds_allowlist_filter — glob real (fnmatch) para o allowlist do ds-gate.sh.

Lê linhas `path:lineno:conteúdo` (saída de `grep -rEn`) em stdin e devolve em
stdout só as que NÃO casam nenhum padrão passado em argv. Um arquivo .py
separado (em vez de `python3 - <<HEREDOC`) é INTENCIONAL: `python3 -` lê o
PRÓPRIO PROGRAMA de stdin — um heredoc anexado a esse invocação consome
stdin para carregar o source e o `sys.stdin` do programa em execução chega
vazio, descartando silenciosamente TODA a entrada do pipe (bug real
encontrado e corrigido nesta rodada, H2/A6.3 — confirmado com
`printf 'a\\nb\\n' | python3 - <<'EOF' ... EOF` → `sys.stdin.readlines()`
retorna `[]`). Um script de arquivo real não tem esse conflito: argv carrega
os padrões, stdin fica livre para o pipe do grep.

Uso: grep -rEn ... | python3 ds_allowlist_filter.py '<glob1>' '<glob2>' ...
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
