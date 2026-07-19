#!/usr/bin/env python3
"""completion-gate — Stop hook (dual-runtime: Claude Code e Codex).

Bloqueia o fim de turno quando a ÚLTIMA mensagem do assistente contém um claim
de conclusão de nível de plano (100%, "plano executado", "tudo corrigido",
"all done", "task complete"...) sem o bloco de evidência da skill
`prova-de-conclusao` (sentinel completo `PROVA-DE-CONCLUSAO: x/y PASS,
gaps: [...]`). Origem: auditoria de fricção 2026-07-03, cluster 1 (42
incidentes de overclaim em 12 sessões).

Payload dual-runtime (confirmado via WebFetch learn.chatgpt.com/docs/hooks
nesta sessão — H3/A1-2): o Claude Code manda `transcript_path` (JSONL) e NÃO
manda `last_assistant_message`; o Codex manda os dois campos, mas
`transcript_path` pode vir `null` — `last_assistant_message` (string) é a
única fonte confiável de texto do turno nesse runtime. Por isso o campo
`last_assistant_message`, quando presente e não-vazio, tem PRIORIDADE sobre
o parsing de transcript (que é Claude-specific e não existe no payload
Codex real); só cai para o parsing de transcript quando esse campo está
ausente/vazio (caminho Claude, inalterado).

Contrato: exit 0 = permite parar; exit 2 = bloqueia (stderr vai para o modelo).
`stop_hook_active` true = já bloqueou uma vez neste turno → permite (evita loop).
Fail-open: qualquer erro interno permite parar.
"""
import json
import re
import sys

# Claims de nível de PLANO apenas — claims de mudança única ("arquivo corrigido")
# passam de propósito; para esses vale a skill `verify`. PT e EN (H3/A1-2:
# payload Codex pode chegar em inglês; a regex só cobria português).
CLAIM_RE = re.compile(
    r"""(?ix)(
        \b100\s*\%
      | \bplano\s+(?:foi\s+)?(?:executado|conclu[ií]do|finalizado)
      | \bexecutad[oa]s?\s+(?:integralmente|por\s+completo|na\s+[ií]ntegra)
      | \btudo\s+(?:foi\s+)?(?:implementad|corrigid|finalizad|conclu[ií]d)
      | \btodos?\s+os\s+(?:itens|gaps|p0s?|pontos|cr[ií]ticos)\s+(?:foram\s+)?
            (?:fechad|resolvid|corrigid|implementad|conclu[ií]d)
      | \bpronto\s+para\s+(?:produ[çc][ãa]o|homolog|deploy|entrega)
      | \bgaps?\s+zerad
      | \bimplementa[çc][ãa]o\s+(?:est[áa]\s+)?completa
      | \bplan\s+is\s+(?:complete|executed|finished|done)
      | \ball\s+(?:done|fixed|complete[d]?|resolved|finished|implemented)
      | \beverything\s+(?:is\s+|has\s+been\s+)?(?:done|fixed|complete[d]?|resolved|implemented)
      | \btask\s+(?:is\s+)?complete[d]?
      | \bfully\s+(?:implemented|fixed|resolved|complete)
      | \bready\s+for\s+(?:production|deploy(?:ment)?|release)
      | \b(?:all\s+)?gaps?\s+(?:are\s+)?(?:zero|none|closed)
      | \bimplementation\s+is\s+complete
    )"""
)
# Sentinel EXIGE o formato completo (não basta "x/y" cru): número/número,
# literal PASS, vírgula, literal gaps: — H3/A1-2, achado real: a regex
# anterior aceitava qualquer "0/999" como se fosse o bloco de evidência.
SENTINEL_RE = re.compile(
    r"PROVA-DE-CONCLUSAO:\s*\d+\s*/\s*\d+\s*PASS\s*,\s*gaps\s*:", re.IGNORECASE
)
TAIL_BYTES = 2_000_000  # transcripts chegam a 45MB; só o final interessa


def assistant_texts_from_tail(path):
    """Últimos textos do assistente (main loop, sem sidechains), mais recente por último."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    texts = []
    for line in raw.splitlines():
        if '"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue  # primeira linha do tail pode vir cortada
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        txt = " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if txt:
            texts.append(txt)
    return texts


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0  # já bloqueamos uma vez neste turno

    last_assistant_message = data.get("last_assistant_message")
    if isinstance(last_assistant_message, str) and last_assistant_message.strip():
        # Codex: o payload já traz o texto final do turno; transcript_path
        # pode vir null e, mesmo quando presente, não é o formato JSONL que
        # assistant_texts_from_tail sabe parsear (esse é Claude-specific).
        texts = [last_assistant_message]
    else:
        transcript = data.get("transcript_path")
        if not transcript:
            return 0
        texts = assistant_texts_from_tail(transcript)
        if not texts:
            return 0
    last = texts[-1]
    if not CLAIM_RE.search(last):
        return 0
    # sentinel pode estar na própria mensagem ou logo antes (veredito em msg anterior)
    if any(SENTINEL_RE.search(t) for t in texts[-3:]):
        return 0
    sys.stderr.write(
        "COMPLETION-GATE: claim de conclusão de plano sem bloco de evidência.\n"
        "Antes de declarar 100%/plano executado/tudo corrigido, rode a skill "
        "`prova-de-conclusao`: para cada item declarado, evidência DESTA sessão "
        "(comando + exit code, grep com path+Linha, contagem de testes, manifest "
        "do ui-evidence, curl na URL de prod) numa tabela, terminando com a linha "
        "literal `PROVA-DE-CONCLUSAO: <x>/<y> PASS, gaps: [ids ou 'nenhum']`.\n"
        "Se não há evidência para um item, ele é gap — reformule o veredito sem o "
        "claim de conclusão em vez de fabricar certeza.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
