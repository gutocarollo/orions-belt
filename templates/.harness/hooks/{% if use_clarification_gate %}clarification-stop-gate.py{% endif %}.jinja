#!/usr/bin/env python3
"""Stop hook: decisao entregue ao dono exige bloco D[n] completo, nunca forma seca.

Irmao de `clarification-plan-gate.py` (PreToolUse/AskUserQuestion): aquele cobre o caminho de
FERRAMENTA (o contrato carregado antes de perguntar); este cobre o caminho de PROSA — o "known
limit" declarado la ("decisions asked as PROSE never call a tool, so this gate never sees them").
Juntos fecham os dois caminhos. Roda em Claude E Codex (evento Stop existe nos dois).

Portado de ui-tokenizer-v2/tools/hooks/clarification-gate.py (LEI ZERO) com as
3 correcoes da falha de 2026-07-31, quando o agente terminou o turno com
"Decisoes que continuam suas: [4 bullets de 1 linha]... Aguardando sua
avaliacao" e nenhum gate disparou:

  1. O original so existia/registrava no OUTRO repo — esta copia registra no
     settings.json DESTE projeto (hook dispara pelo project dir da sessao).
  2. O original so detectava PERGUNTA de escolha (pattern + "?"). Handoff de
     decisao sem pergunta ("aguardando sua decisao" + lista de pendencias)
     passava. Agora ha uma segunda classe: HANDOFF + sinal de decisoes abertas,
     sem exigir interrogacao.
  3. Os patterns ASCII nao casavam texto acentuado ("avanço", "opção",
     "você") — falso-negativo conhecido. Agora o corpo e NFD-normalizado
     (acentos removidos) antes do match.

O gate mede no texto final do turno:
  (a) pergunta de ESCOLHA ao dono?  OU  (b) handoff de decisoes abertas?
  Se sim a qualquer um: exige bloco `### D[n]` com os elementos obrigatorios
  (labels em portugues — mesmo contrato da skill grill-me).

Nao conta: pergunta retorica em explicacao, pergunta em bloco de codigo ou
citacao, pedido de credencial/acesso (nao ha opcao a comparar), parada
"aguardando avaliacao do plano" SEM decisoes abertas enumeradas.

Contrato: exit 0 = libera; exit 2 = bloqueia (stderr vai para o modelo).
`stop_hook_active` true = ja bloqueou neste turno -> libera, evita loop.
"""
import json
import re
import sys
import unicodedata

# Perguntas que pedem ESCOLHA do dono (exigem tambem "?" no corpo).
CHOICE_PATTERNS = [
    # verbo de 1a pessoa do presente + interrogacao = pedido de permissao.
    r"\b(?:sigo|crio|implemento|executo|rodo|aplico|migro|comeco|avanco|prossigo|"
    r"gero|escrevo|renomeio|removo|adiciono|instalo|commito|pusho)\b",
    r"\bquer\s+que\s+eu\b",
    r"\bprefere\b",
    r"\bqual\s+(?:voce|vc|deles|delas|opcao|caminho|dos)",
    r"\b(?:posso|devo|faco)\b",
    r"\bautoriza\b",
    r"\bconfirma\b",
    r"\bA\s+ou\s+B\b",
    # ingles (installs do orions-belt com harness_language=en)
    r"\bshould\s+i\b",
    r"\b(?:do\s+you\s+)?want\s+me\s+to\b",
    r"\bwhich\s+(?:do\s+you\s+prefer|one|option|approach)\b",
    r"\bA\s+or\s+B\b",
]

# Handoff: o turno termina devolvendo a bola ao dono (NAO exige "?").
HANDOFF_PATTERNS = [
    r"\baguardando\s+(?:sua\s+|a\s+|o\s+)?(?:decisao|decisoes|avaliacao|escolha|resposta|aprovacao|ordem)",
    r"\bdecis(?:ao|oes)\s+(?:que\s+)?(?:continuam?\s+su|ficam?\s+su|sao\s+su|do\s+dono|pendente|em\s+aberto)",
    r"\bcabe\s+a\s+voce\b",
    r"\bo\s+dono\s+decide\b",
    r"\bso\s+(?:voce|o\s+dono)\s+(?:pode\s+)?(?:decide|destrava|resolve)",
    # Handoff DECLARATIVO — as formas medidas em 2026-08-02, que passaram batido
    # porque nenhuma tem "?" nem as palavras acima.
    r"\bse\s+voce\s+(?:me\s+)?(?:disser|escolher|responder|definir|aprovar)",
    r"\bbloquead[oa]s?\s+em\s+voce\b",
    r"\b(?:bloqueia|trava|travam|impede)\s+(?:a\s+|o\s+|as\s+|os\s+)?\w*\s*(?:migra|decis|execu|transic)",
    r"\bdepende\s+d[ae]\s+(?:voce|sua\s+(?:escolha|decisao|resposta))",
    r"\b(?:continua|continuam|segue|seguem)\s+esperando\s+(?:sua|a\s+sua|voce)",
    r"\besperando\s+(?:sua\s+)?(?:escolha|decisao|resposta|aprovacao)",
    r"\bseu\s+ato\s+por\s+contrato\b",
]

# Sinal de que ha DECISOES/OPCOES enumeradas em jogo (handoff so bloqueia com isso).
DECISION_SIGNALS = [
    r"\bD-?\d+\b",
    r"\bD-[a-z]\b",
    r"\bopc(?:ao|oes)\s+[A-C]\b",
    r"\bdecis(?:ao|oes)\b",
    r"\bescolh(?:a|as|er)\b",
]

# O bloco obrigatorio e seus elementos (contrato da skill grill-me).
# Labels aceitos em pt E en — a skill canonica do orions-belt e en, os
# harness pt usam os labels traduzidos; o gate nao pode punir nenhum dos dois.
D_BLOCK = re.compile(r"^#{2,4}\s*D[-\d]", re.MULTILINE)
REQUIRED_ELEMENTS = {
    "Canon": r"\*\*C[a]?non",
    "Comportamento/Behavior": r"\*\*(?:Comportamento|Behavior)",
    # Ordem das palavras nao e o contrato — o conteudo e. "Bom aplicado" diz o
    # mesmo que "Exemplo aplicado bom", e reprovar por ordem produz bloqueio
    # falso sem ganhar nada.
    "Exemplo aplicado bom/Applied good example": r"\*\*(?:Exemplo aplicado bom|Bom aplicado|Applied good example|Good applied)",
    "Exemplo aplicado ruim/Applied bad example": r"\*\*(?:Exemplo aplicado ruim|Ruim aplicado|Applied bad example|Bad applied)",
    "Quando escolher/When to choose": r"\*\*(?:Quando escolher|When to choose)",
    "Minha recomendacao/Recommended answer": r"\*\*(?:Minha recomenda|Recomend[oa]|Recommended answer|My recommendation)",
}

FORMATO = (
    "### D1 — [pergunta concreta da decisao]\n\n"
    "**Canon:** [docs canonicos grepados + veredito: DECIDE (retirar) / SILENTE / CONFLITA]\n"
    "**Evidencia:** [path + Linha N / query / ferramenta+consulta]\n"
    "**Destrava:** [o que fica bloqueado sem esta decisao]\n\n"
    "**Opcao A — [nome]**\n"
    "- **Comportamento:** o que o sistema/processo passa a fazer.\n"
    "- **Exemplo aplicado bom:** no caso REAL [arquivo/token/rota/comando], acontece X.\n"
    "- **Exemplo aplicado ruim:** no caso REAL [...], acontece Y.\n"
    "- **Quando escolher:** se a prioridade for Z.\n\n"
    "**Opcao B — [nome]** (os mesmos itens)\n"
    "**Opcao C** quando A e B isoladas forem insuficientes.\n\n"
    "**Minha recomendacao:** [qual, e por que, com o dado que sustenta].\n\n"
    "Exemplo aplicado = entidade, arquivo, token, rota, comando ou tela REAL do "
    "contexto. Analogia generica nao vale.\n"
    "Se a decisao NAO precisa do dono — decida com evidencia, execute e relate "
    "a escolha em vez de perguntar.\n"
)


def fold(text: str) -> str:
    """NFD-normaliza e remove combining marks: 'opção' -> 'opcao'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def strip_code_and_quotes(text: str) -> str:
    """Remove fenced code, INLINE code e blockquotes: pergunta ali nao e pergunta ao dono.

    Inline code entrou depois do 1o disparo real (2026-07-31): um `?` dentro de
    crase num relatorio satisfez a condicao de interrogacao e virou falso motivo.
    """
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"^\s*>.*$", " ", text, flags=re.MULTILINE)
    #
    # TRECHO ENTRE ASPAS tambem sai, e entrou no 2o disparo real (2026-08-02):
    # o turno que EXPLICAVA este conserto citou o padrao novo como
    # *"se voce me disser"* e o gate bloqueou a propria documentacao dele. Frase
    # entre aspas esta sendo CITADA, nao praticada — mesmo princípio da crase.
    #
    # So spans curtos (<=120 chars) e numa linha: aspas de abertura sem
    # fechamento na mesma linha nao devem engolir o resto do turno.
    text = re.sub(r'"[^"\n]{0,120}"', " ", text)
    text = re.sub(r"[\u201c\u201d][^\u201c\u201d\n]{0,120}[\u201c\u201d]", " ", text)
    return text


def assistant_texts_from_tail(path, limit=400):
    texts = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        return texts
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            txt = "".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
            if txt.strip():
                texts.append(txt)
    return texts


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0

    last_assistant_message = data.get("last_assistant_message")
    if isinstance(last_assistant_message, str) and last_assistant_message.strip():
        texts = [last_assistant_message]
    else:
        transcript = data.get("transcript_path")
        if not transcript:
            return 0
        texts = assistant_texts_from_tail(transcript)
        if not texts:
            return 0

    raw = texts[-1]
    body = fold(strip_code_and_quotes(raw))

    # Verbo e "?" precisam estar na MESMA frase ("Sigo criando os 32 tokens?").
    # Verbo em narracao de relatorio + "?" incidental noutro paragrafo nao e
    # pedido de permissao — falso positivo do 1o disparo real (2026-07-31).
    choice_hits = [
        p for p in CHOICE_PATTERNS
        if re.search(p + r"[^.!?\n]{0,160}\?", body, re.IGNORECASE)
    ]
    is_choice = bool(choice_hits)

    handoff_hits = [p for p in HANDOFF_PATTERNS if re.search(p, body, re.IGNORECASE)]
    has_decisions = any(re.search(p, body, re.IGNORECASE) for p in DECISION_SIGNALS)
    is_handoff = bool(handoff_hits) and has_decisions

    # A INVERSAO (2026-08-02). Antes: o bloco D[n] so era conferido DEPOIS de o
    # gate reconhecer uma pergunta. Isso deixava passar o caso mais comum de
    # todos — apresentar decisao de forma DECLARATIVA, sem "?" e sem as palavras
    # exatas de handoff.
    #
    # Medido no proprio historico: um turno com "### D3", rotulos "**Bom
    # aplicado:**"/"**Ruim aplicado:**" (fora do contrato) e recomendacao inline
    # em italico passou com exit 0 — o bloco estava INCOMPLETO e ninguem olhou,
    # porque a deteccao de pergunta falhou primeiro. E o turno seguinte entregou
    # DUAS decisoes abertas sem bloco algum e tambem passou.
    #
    # Agora: bloco presente e SEMPRE conferido. A deteccao de pergunta/handoff
    # decide apenas o caso "nao ha bloco nenhum".
    if D_BLOCK.search(raw):
        faltando = [
            nome for nome, rx in REQUIRED_ELEMENTS.items()
            if not re.search(rx, fold(raw), re.IGNORECASE)
        ]
        if not faltando:
            return 0
        sys.stderr.write(
            "CLARIFICATION-GATE: o bloco D[n] existe mas esta incompleto.\n"
            f"Faltam os elementos: {', '.join(faltando)}.\n"
            "Cada opcao precisa de Comportamento, Exemplo aplicado bom, Exemplo "
            "aplicado ruim, Quando escolher — e o turno precisa de UMA "
            "**Minha recomendacao** com o caminho que voce escolheria e por que.\n"
        )
        return 2

    if not is_choice and not is_handoff:
        return 0

    motivo = (
        f"pergunta de escolha (padrao: {choice_hits[0]})" if is_choice
        else f"handoff de decisoes abertas (padrao: {handoff_hits[0]})"
    )
    sys.stderr.write(
        "CLARIFICATION-GATE: voce esta entregando uma decisao ao dono sem o "
        f"bloco D[n].\nDetectado: {motivo}\n\n"
        "Pergunta seca E handoff seco sao proibidos (skill grill-me). "
        "Reescreva o final do turno assim:\n\n" + FORMATO
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
