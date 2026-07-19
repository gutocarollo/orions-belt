#!/usr/bin/env python3
"""lei-zero-kickoff — UserPromptSubmit hook.

Quando o prompt parece kickoff de feature/refactor e NÃO menciona a LEI ZERO,
injeta o protocolo compacto como contexto (stdout de UserPromptSubmit vira
contexto do modelo). Automatiza o que o dono do harness-doador colava à mão
toda sessão. Origem: auditoria de fricção do harness-doador, cluster 5.
Fail-open: qualquer erro → exit 0 sem output.
"""
import json
import re
import sys

KICKOFF_RE = re.compile(
    r"(?i)\b("
    r"implemente|implementar|desenvolv[ae]|crie|criar|adicione|adicionar"
    r"|monte\s+um\s+plano|nova\s+(feature|funcionalidade)"
    r"|refator[ae]|migr[ae]r?|constru[aií]"
    r"|implement|build\s+a|add\s+(a\s+)?feature"
    r")\b"
)
# prompts curtos ("continue", "corrija", colas de auditoria) não são kickoff
MIN_LEN = 25

PROTOCOL = """<lei-zero-protocolo>
LEI ZERO (AGENTS.md/CLAUDE.md §0) — antes de implementar qualquer feature não trivial:
1. PESQUISAR soluções maduras existentes (GitHub/awesome-lists via plugin last30days quando disponível; docs oficiais via Context7). Cada feature investigada individualmente.
2. Portar/copiar/reaproveitar libs, código e padrões validados. Implementar do zero SÓ se nada for reaproveitável — e declarar por quê.
3. Verificar o que o REPO JÁ TEM antes de criar (grep no código, lockfile/manifest de dependências, blocos ⭐ REFERÊNCIA CANÔNICA do AGENTS.md/CLAUDE.md).
4. Migrações/mudanças transversais: SEQUENCIAIS, 1 por vez, testadas (§0.6, §14).
Se o plano final reinventa algo que existe, o plano está errado.
</lei-zero-protocolo>"""


def main():
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt") or ""
    except Exception:
        return 0
    if len(prompt) < MIN_LEN:
        return 0
    low = prompt.lower()
    if "lei zero" in low or "lei-zero" in low:
        return 0  # usuário já invocou a lei explicitamente
    if not KICKOFF_RE.search(prompt):
        return 0
    print(PROTOCOL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
