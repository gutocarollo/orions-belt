---
title: Migração dos tokens de contrato PT→EN precisa de janela de alias antes de entrar
status: aberto
quem_resolve: dono
severidade: alta
bloqueia: adocao da branch feat/en-tokens-and-docs-sync (10 commits, nunca pushada)
fonte: engine/contract/scripts/agent_swarm_ledger.py:102
citacao: allowed = EVENT_STATUSES.get((entry["loop"], entry["event"]))
updated: 2026-08-06
---

## O que falta

A migração do vocabulário de contrato de PT para EN (`SATISFEITO`→`APPROVED`,
`CORRIGIR`→`FIX`, `PROVA-DE-CONCLUSAO`→`PROOF-OF-COMPLETION`) existe pronta em
`c430e9b`, na branch `feat/en-tokens-and-docs-sync`. **Não foi adotada** neste ciclo por
dois motivos medidos.

## Motivo 1 — é mudança quebrante de contrato de dados, sem caminho de migração

O validador que os projetos instalados já rodam faz rejeição dura na linha citada
acima: `if allowed is not None and entry["status"] not in allowed: raise SystemExit(...)`.
O `60ac47f` melhora a mensagem de erro (`legacy_token_hint`), mas **não aceita** o
token antigo — não há janela de alias.

Medido em 2026-08-06 nos projetos instalados desta estação:

```
ledgers agent-swarm com token PT: 13 arquivos · 47 eventos
  29 × "CORRIGIR"     18 × "SATISFEITO"
repos: WhatsApp_Agent_Chat_slim-shape · makers-ai-hub · harness-wiki
```

Comando que reproduz:

```bash
find <raiz-dos-projetos> -path "*agent-swarm*" -name loop.jsonl \
  -exec grep -ohE '"status": "[A-Z_]+"' {} \; | sort | uniq -c
```

Se qualquer um desses projetos rodar `copier update` puxando a migração,
`read_and_validate()` percorrendo aquele `loop.jsonl` bate em `"CORRIGIR"` contra um
`EVENT_STATUSES` que só aceita `"FIX"` → `SystemExit`. O ledger histórico fica ilegível.

Segundo vetor, com atualização parcial: `templates/.harness/hooks/completion-gate.py`
procura o sentinela por regex, e a prosa da skill `prova-de-conclusao` instrui o modelo a
emitir a string literal. Se só a metade-hook do update chegar, o gate passa a procurar
`PROOF-OF-COMPLETION` enquanto a skill manda emitir `PROVA-DE-CONCLUSAO` — e o gate
bloqueia toda alegação de conclusão, para sempre.

## Motivo 2 — o commit não entregou o DRY que a mensagem dele promete

`engine/contract/tokens.py` foi criado como "fonte única" e, medido na ponta da branch,
os quatro frozensets dele têm **zero importadores**:

```bash
git grep -n "from contract.tokens" b540368 -- '*.py'
# engine/contract/scripts/agent_swarm_ledger.py:33: from contract.tokens import legacy_token_hint
git grep -n "PLAN_OUTCOMES" b540368 -- '*.py' | grep import
# engine/integration/council_pipeline.py:26: from engine.graph.runtime import ... PLAN_OUTCOMES ...
```

O único import é de uma função de mensagem de erro; `council_pipeline.py` continua
importando os conjuntos de `engine.graph.runtime`. Resultado: `tokens.py` é uma **quarta
cópia paralela** dos mesmos valores, ao lado de `runtime.py`, dos dois
`agent_swarm_ledger.py` e dos dicts inline do `council_pipeline.py`. A migração
**adicionou** duplicação em vez de eliminá-la.

## O que resolver quando isto for retomado

1. `EVENT_STATUSES` aceita PT **e** EN por uma versão declarada, com data de remoção — o
   `legacy_token_hint` vira aviso, não `SystemExit`.
2. O sentinela do `completion-gate.py` casa os dois formatos, para que atualização parcial
   (hook novo + prosa antiga) não trave o gate.
3. `tokens.py` passa a ser importado de verdade: `runtime.py`, os dois ledgers e
   `council_pipeline.py` derivam dele em vez de repetir os literais.
4. Só então a troca dos valores, com os `loop.jsonl` existentes ainda legíveis.

## O que já foi aproveitado da mesma branch

Cherry-pickados neste ciclo, por serem independentes da migração: `f588e3e` (adapter do
Understand Anything), `a9c6860` (ratchet de topologia de docs), `354c3c3` (gate de frescor
do README), `2809e45` (roster de hooks nos capítulos 01-03) e o hunk do `--vcs-ref` do
`60ac47f`. O `559609b` foi descartado: a entrada `_exclude` que ele diz adicionar já
existia, e o commit apenas a duplicava.
