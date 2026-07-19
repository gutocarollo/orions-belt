#!/usr/bin/env bash
# =============================================================================
# ds-gate.sh — Gate genérico de tokenização de design system (motor).
# -----------------------------------------------------------------------------
# PORTADO de apps/web/scripts/ds-gate.sh (harness-doador de referência) —
# plano de resgate §R1a. Prova "quanto do design está tokenizado" de forma
# DETERMINÍSTICA: conta, por dimensão, cores/valores de design HARDCODED que
# driblam os tokens Tailwind/CSS-vars. Modo RATCHET: compara com
# .ds-baseline.txt (dentro do diretório do app web) e FALHA (exit 1) só se
# alguma dimensão AUMENTAR. Sem baseline (1ª execução), roda em modo
# report-only e nunca falha — o ratchet nasce do primeiro
# `--update-baseline` explícito, não de um valor chutado.
#
# GENERICIDADE (vs. a versão-fonte): nenhuma string de marca hardcoded. O
# diretório do app web vem de HARNESS_WEB_APP_DIR (.harness/harness.conf,
# lido em runtime via _tooling_conf.py — mesmo diretório deste script) ou de
# `--dir <path>` explícito. Exclusões de marca (ex.: nome de escala de cor
# customizada, path do arquivo de tokens) vêm de DS_BRAND_EXCLUDE_PATTERNS
# (CSV de ERE) — default vazio, engine mais estrito quando não configurado
# (nunca mais permissivo por omissão).
#
# Uso:
#   bash .harness/lib/ds-gate.sh [--dir <web-app-dir>] [check|--report|--update-baseline]
#
# Allowlist (2 níveis, ambos versionados/auditáveis, DENTRO do diretório do
# app web):
#   - inline: comentar a linha com  // ds-allow: <motivo>   (ou /* ds-allow: */)
#   - por caminho: globs em .ds-allowlist (um por linha; '#'=comentário)
# =============================================================================
set -uo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${HARNESS_PROJECT_ROOT:-${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}}"
if [ -z "$PROJECT_ROOT" ]; then
  echo "ds-gate: não foi possível resolver a raiz do projeto (nem HARNESS_PROJECT_ROOT/CLAUDE_PROJECT_DIR nem git repo) — fail-open." >&2
  exit 0
fi

CONF_PY="$LIB_DIR/_tooling_conf.py"
_conf_get() {
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    HARNESS_PROJECT_ROOT="$PROJECT_ROOT" python3 "$CONF_PY" get "$1" "$2" 2>/dev/null && return 0
  fi
  echo "$2"
}
_conf_getcsv() {
  if command -v python3 >/dev/null 2>&1 && [ -f "$CONF_PY" ]; then
    HARNESS_PROJECT_ROOT="$PROJECT_ROOT" python3 "$CONF_PY" getcsv "$1" "" 2>/dev/null
  fi
}

WEB_APP_DIR_ARG=""
if [[ "${1:-}" == "--dir" ]]; then
  WEB_APP_DIR_ARG="${2:-}"
  shift 2 2>/dev/null || shift "$#"
fi
WEB_APP_DIR="${WEB_APP_DIR_ARG:-$(_conf_get HARNESS_WEB_APP_DIR .)}"
WEB_APP_DIR="${WEB_APP_DIR%/}"
[ -z "$WEB_APP_DIR" ] && WEB_APP_DIR="."

TARGET_DIR="$PROJECT_ROOT"
[ "$WEB_APP_DIR" != "." ] && TARGET_DIR="$PROJECT_ROOT/$WEB_APP_DIR"
if [ ! -d "$TARGET_DIR" ]; then
  echo "ds-gate: diretório do app web ($TARGET_DIR) não existe — nada a checar (fail-open)."
  exit 0
fi
cd "$TARGET_DIR" || { echo "ds-gate: falha ao entrar em $TARGET_DIR — fail-open." >&2; exit 0; }

DS_BRAND_EXCLUDE_ERE="$(_conf_getcsv DS_BRAND_EXCLUDE_PATTERNS | tr ',' '|')"
_brand_filter() {
  if [[ -n "$DS_BRAND_EXCLUDE_ERE" ]]; then
    grep -viE "$DS_BRAND_EXCLUDE_ERE"
  else
    cat
  fi
}

ROOT="."
SRC_GLOB='--include=*.tsx --include=*.ts'
EXCLUDE='--exclude-dir=node_modules --exclude-dir=.next --exclude-dir=dist --exclude-dir=build --exclude-dir=scripts'
BASELINE=".ds-baseline.txt"
ALLOWFILE=".ds-allowlist"
MODE="${1:-check}"

# allowlist por caminho: um GLOB real por linha (fnmatch), não substring.
#
# H2/A6.3 (auditoria adversarial pós-v1.0.0, bypass REPRODUZIDO): a versão
# anterior lia `.ds-allowlist` e fazia `grep -vF` (substring LITERAL) contra
# `$ROOT/<linha>` — um padrão como `legacy/**` nunca casava nenhum path real
# porque a substring "**" não existe em nenhum caminho de verdade; a doc
# prometia "glob" (comentário no topo deste arquivo e docs/manual/
# 05-hooks-posttooluse.md) mas o allowlist era, na prática, inoperante para
# qualquer entrada com wildcard. Fix: filtra via `.harness/lib/
# ds_allowlist_filter.py` (fnmatch real, mesma dependência que
# `_tooling_conf.py` já exige) — cada padrão casa contra o path relativo
# (antes do primeiro ':' na saída do grep -n). `fnmatch` não trata `/` como
# especial (`*`/`**` casam qualquer sufixo, incluindo subdiretórios) —
# suficiente para "aceitar uma pasta/arquivo legado inteiro", documentado
# aqui em vez de prometer semântica de `pathlib.Path.match`/glob de shell
# (que PARARIA em `/` para um `*` único). Script SEPARADO de propósito (não
# `python3 - <<HEREDOC` inline): `python3 -` lê o PRÓPRIO PROGRAMA de stdin
# — um heredoc consome stdin pra carregar o source e `sys.stdin` chega
# vazio ao programa, descartando toda a entrada do pipe do grep em
# silêncio (bug real encontrado nesta rodada ao testar a 1ª versão do fix
# — ver comentário no topo de ds_allowlist_filter.py).
build_allow_patterns() {
  if [[ -f "$ALLOWFILE" ]]; then
    grep -vE '^\s*#|^\s*$' "$ALLOWFILE" 2>/dev/null
  fi
}
mapfile -t ALLOW_PATTERNS < <(build_allow_patterns)

_allowlist_filter() {
  if [[ ${#ALLOW_PATTERNS[@]} -eq 0 ]] || ! command -v python3 >/dev/null 2>&1 || [[ ! -f "$LIB_DIR/ds_allowlist_filter.py" ]]; then
    cat
    return
  fi
  python3 "$LIB_DIR/ds_allowlist_filter.py" "${ALLOW_PATTERNS[@]}"
}

# conta ocorrências de um ERE em .ts/.tsx, excluindo dirs, `ds-allow:`,
# paths allowlistados (glob real, ver _allowlist_filter) e o exclude de
# marca configurado (DS_BRAND_EXCLUDE_PATTERNS)
count() {
  local ere="$1"; shift
  local extra_filter="${1:-cat}"
  local out
  out=$(grep -rEn $SRC_GLOB $EXCLUDE "$ere" "$ROOT" 2>/dev/null | grep -v 'ds-allow:')
  printf '%s\n' "$out" | _allowlist_filter | eval "$extra_filter" | _brand_filter | grep -c .
}

# ---- Dimensões (ERE + filtro extra). Engine genérico Tailwind/shadcn. -------
declare -A DIMS
declare -A FILT
DIMS[color-gray]='(^|[^-a-z])(bg|text|border|ring|divide|from|via|to|fill|stroke)-gray-(50|100|200|300|400|500|600|700|800|900|950)'
FILT[color-gray]='cat'
# color-wb conta SÓ formas SÓLIDAS: white/black com alpha (/N ou /[..]) é o idioma
# translúcido (glass/scrim/hairline sobre mídia ou superfície) — theme-independent
# por definição. Sólido = dívida real (deveria ser token semântico).
DIMS[color-wb]='(bg|text|border|ring|from|via|to|fill|stroke)-(white|black)([^a-z0-9/[-]|$)'
FILT[color-wb]='cat'
DIMS[color-named]='(bg|text|border|ring|from|via|to|fill|stroke)-(red|green|blue|emerald|amber|yellow|orange|indigo|purple|violet|rose|sky|cyan|teal|pink|lime|fuchsia)-[0-9]{2,3}'
FILT[color-named]='cat'
DIMS[color-hex]='#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([0-9]'
# alphas NEUTROS rgba(0,0,0,x)/rgba(255,255,255,x) = idioma sombra/scrim/glass
# (theme-independent) — heurística GENÉRICA de CSS, não específica de marca.
FILT[color-hex]='grep -viE "rgba?\\(\\s*0\\s*,\\s*0\\s*,\\s*0|rgba?\\(\\s*255\\s*,\\s*255\\s*,\\s*255|rgb\\(\\s*0\\s+0\\s+0|rgb\\(\\s*255\\s+255\\s+255"'
DIMS[typography-px]='text-\[[0-9.]+px\]'
FILT[typography-px]='cat'
DIMS[spacing-rhythm]='(gap|space-x|space-y|p|px|py|pl|pr|pt|pb|m|mx|my|mt|mb|ml|mr)-\[[0-9][^]]*(px|rem)\]'
FILT[spacing-rhythm]='cat'
DIMS[radius-shadow]='(rounded(-[a-z]+)?-\[|shadow-\[|border(-[a-z]+)?-\[[0-9]|ring-\[[0-9])'
FILT[radius-shadow]='grep -v "var(--"'
DIMS[zindex]='z-\[[0-9]+\]|(^|[^a-z-])z-[0-9]{2,}'
FILT[zindex]='grep -vE "z-\(--z-"'
DIMS[motion]='(duration|ease)-\['
FILT[motion]='grep -v "var(--"'

ORDER=(color-gray color-wb color-named color-hex typography-px spacing-rhythm radius-shadow zindex motion)

# ---- baseline I/O ------------------------------------------------------------
declare -A BASE
if [[ -f "$BASELINE" ]]; then
  while IFS='=' read -r k v; do [[ -n "$k" ]] && BASE[$k]="$v"; done < "$BASELINE"
fi

printf '%-16s %8s %10s   %s\n' "DIMENSÃO" "ATUAL" "BASELINE" "STATUS"
printf '%s\n' "------------------------------------------------------------"
FAIL=0; TOTAL=0
declare -A NOW
for d in "${ORDER[@]}"; do
  n=$(count "${DIMS[$d]}" "${FILT[$d]}")
  NOW[$d]=$n; TOTAL=$((TOTAL+n))
  b="${BASE[$d]:-}"
  if [[ "$MODE" == "--report" || -z "$b" ]]; then
    printf '%-16s %8s %10s   %s\n' "$d" "$n" "${b:-—}" "report"
  elif (( n > b )); then
    printf '%-16s %8s %10s   ✗ SUBIU (+%d)\n' "$d" "$n" "$b" "$((n-b))"; FAIL=1
  elif (( n < b )); then
    printf '%-16s %8s %10s   ✓ melhorou (-%d)\n' "$d" "$n" "$b" "$((b-n))"
  else
    printf '%-16s %8s %10s   ✓ ok\n' "$d" "$n" "$b"
  fi
done
printf '%s\n' "------------------------------------------------------------"
printf '%-16s %8s\n' "TOTAL" "$TOTAL"
echo "(0 em todas = 100% tokenizado. Ratchet: baseline só encolhe. Sem baseline = report-only, nunca falha.)"

if [[ "$MODE" == "--update-baseline" ]]; then
  : > "$BASELINE"
  for d in "${ORDER[@]}"; do echo "$d=${NOW[$d]}" >> "$BASELINE"; done
  echo ">> baseline atualizado em $TARGET_DIR/$BASELINE"
  exit 0
fi
[[ "$MODE" == "--report" ]] && exit 0
exit $FAIL
