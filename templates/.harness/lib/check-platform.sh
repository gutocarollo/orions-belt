#!/usr/bin/env bash
# check-platform.sh — preflight de plataforma (M3/H4, auditoria adversarial).
#
# O PROBLEMA: os hooks/scripts deste framework (`.harness/hooks/`,
# `.harness/lib/`) dependem de um subconjunto GNU/Linux específico --
# `mapfile`/`declare -A` (Bash >=4; macOS ships Bash 3.2 por licença GPLv3),
# `stat -c` (GNU coreutils; BSD/macOS usa `stat -f`), `date +%s%N`
# (nanossegundos -- só GNU date; BSD date não tem `%N`), `flock` (util-linux,
# Linux -- sem equivalente nativo no macOS) e `python3`. Antes deste script,
# "portátil" não estava DECLARADO em lugar nenhum e a falha de uma dessas
# deps era SILENCIOSA -- um hook rodava, um `stat -c` desconhecido virava
# stderr solto ou um valor errado, e o gate correspondente falhava/virava
# no-op sem nenhum aviso explícito na instalação.
#
# O QUE ESTE SCRIPT FAZ: preflight barato, roda uma vez (na instalação, ou
# a qualquer momento), reporta PASS/FALTA por dependência com o comando de
# fix sugerido. Não tenta portar os hooks para BSD/POSIX puro (fora de
# escopo desta rodada -- ver docs/manual/15-limitacoes-conhecidas.md) --
# só torna a lacuna visível e acionável em vez de descoberta hook-a-hook.
#
# Exit code: 0 = todas as dependências OBRIGATÓRIAS presentes (mesmo com
# avisos leves); 1 = pelo menos uma dependência OBRIGATÓRIA falta -- quem
# chama (harness-install.sh, ou o usuário manualmente) decide se aborta ou
# prossegue ciente do risco (nunca bloqueia sozinho o copier copy/update em
# si, que é agnóstico de plataforma).
set -uo pipefail

MISSING=0
WARN=0

pass() { echo "  OK    $1"; }
fail() { echo "  FALTA $1 -- $2"; MISSING=$((MISSING + 1)); }
warn() { echo "  AVISO $1 -- $2"; WARN=$((WARN + 1)); }

echo "check-platform.sh -- preflight de plataforma do harness"
echo "uname: $(uname -a 2>/dev/null || echo 'indisponivel')"
echo

# --- Bash >= 4 (mapfile, declare -A) ---
if [ -n "${BASH_VERSINFO:-}" ] && [ "${BASH_VERSINFO[0]}" -ge 4 ]; then
  pass "Bash ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]} (>=4, suporta mapfile/declare -A)"
else
  fail "Bash ${BASH_VERSINFO[0]:-desconhecido}.x (<4)" \
    "macOS: brew install bash (Bash do sistema é 3.2, GPLv3); rode os hooks com o Bash do brew, não /bin/bash"
fi

# --- GNU coreutils: stat -c ---
if stat -c %Y . >/dev/null 2>&1; then
  pass "stat -c (GNU coreutils)"
else
  fail "stat -c (GNU coreutils)" \
    "macOS: brew install coreutils, use 'gstat -c' ou prefixe PATH com o coreutils do brew (ver README/manual)"
fi

# --- GNU date: %N (nanossegundos) ---
if date +%s%N 2>/dev/null | grep -qE '^[0-9]{15,}$'; then
  pass "date +%s%N (GNU date, nanossegundos)"
else
  warn "date +%s%N (GNU date, nanossegundos)" \
    "BSD/macOS date não suporta %N; scripts que geram nomes únicos por timestamp (ex.: subagent-throttle.sh) colidem mais fácil sem nanossegundos -- brew install coreutils + 'gdate'"
fi

# --- flock (util-linux) ---
if command -v flock >/dev/null 2>&1; then
  pass "flock (util-linux)"
else
  fail "flock (util-linux)" \
    "macOS: brew install util-linux (flock não existe nativo); sem ele, subagent-throttle.sh/subagent-release.sh não conseguem aquisição atômica de slot"
fi

# --- python3 ---
if command -v python3 >/dev/null 2>&1; then
  pass "python3 ($(python3 --version 2>&1))"
else
  fail "python3" "instale Python 3 (python.org, brew, ou o gerenciador de pacotes da sua distro) -- vários hooks/scripts (.harness/lib/*.py) são stdlib puro em Python"
fi

# --- timeout (GNU coreutils) ---
if command -v timeout >/dev/null 2>&1; then
  pass "timeout (GNU coreutils)"
else
  warn "timeout (GNU coreutils)" \
    "macOS: brew install coreutils, use 'gtimeout' ou prefixe PATH -- usado só em pontos não-bloqueantes (ex.: provision-push.sh)"
fi

echo
if [ "$MISSING" -gt 0 ]; then
  echo "RESULTADO: $MISSING dependência(s) OBRIGATÓRIA(S) faltando, $WARN aviso(s). Ver docs/manual/15-limitacoes-conhecidas.md."
  exit 1
fi
echo "RESULTADO: todas as dependências obrigatórias presentes ($WARN aviso(s) não-bloqueante(s))."
exit 0
