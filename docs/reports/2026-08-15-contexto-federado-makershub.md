# Relatório: do desastre Super R1 ao sistema de contexto federado (makershub)

Data: 2026-08-15 · Caso real do repo-consumidor makershub/fazgraph-canonical-v4 · Status: entregue
(8 de 12 KPIs de ganho provados; 4 dependem de tempo/fila, enumerados ao fim)

## 1. O problema inicial

Em julho-agosto/2026 a refatoração do fluxo de distribuição de leads (Super R1) atravessou dias
de falhas graves em produção — reuniões duplamente agendadas (série semanal 29/9/15/13/8/13/7
pares sobrepostos), fix aplicado que não estava em produção, ledger divergente 12,8%, GC nunca
chamado. A causa sistêmica nomeada pelo dono: **cegueira dos agentes de IA** — nenhum agente
enxergava ao mesmo tempo makershub + airflow + salesforce + postgres + Graph, e a documentação
que deveria dar o norte falhou junto. O pedido original (âncora de 2026-08-14): reconstruir o
caminho reverso commit a commit, alinhar doc ao código ("o código final é a verdade"), entender
por que o glossário/ontologia anterior falhou, e inferir a melhor metodologia para a documentação
entregar SEMPRE o contexto correto.

## 2. O diagnóstico, em números

A investigação (18 agentes sobre 62 PRs + 288 cards; harness de medição construído na hora)
converteu a "cegueira" em três causas mensuráveis:

1. **A resposta não estava escrita.** Gold set de 90 perguntas com gabarito no código: para
   **73/90**, nenhum documento do corpus continha o valor (ex.: `BUSY_CODES = frozenset({'2','3'})`
   só existia em `availability_service.py:94`). Taxa de contexto correto no top-5: **0,144**.
2. **O glossário anterior nunca teve consumidor.** 46h de construção, zero adjudicação, dois
   glossários vivos divergentes; a expansão por sinônimo chegou a DERRUBAR a busca (0,611→0,167
   medido) — o hazard "broader term exige peso menor" que o próprio plano original previa.
3. **O contexto que EXISTIA não era roteado.** Review externo dos PRs 261/262: **12 de 17
   achados** eram "dado já existente pegaria" (classe 1) — incluindo uma lesson escrita pelo
   próprio autor HORAS antes e não consultada; **zero** achados do PR 262 dependiam de contexto
   não-escrito. Nos merges: símbolo removido ressuscitou 3× por merges limpos; `merge-tree`
   previu 0 conflitos onde houve 3; subagente decidiu sobre árvore 55 commits stale.

## 3. A solução final: cinco fontes com papéis medidos + roteamento com recibo

Não se comprou framework nenhum (pesquisa de mercado ago/2026: o stack já era o consenso —
Anthropic/Sourcegraph abandonaram vector-RAG de código por busca agentic; Hindsight lidera o
LongMemEval com 91,4%). O trabalho foi COSTURA:

| Fonte | Papel (medido) | Prova |
|---|---|---|
| Corpus git + BM25/lane exata | literal/identificador | 0,144→**0,978** answerable@5; catraca no CI |
| CodeGraph | estrutura/blast radius | makershub + airflow-dags (6.156 nós) |
| FazGraph local | linhagem/quem-escreve | método formal com aresta grafo→banco |
| Postgres MCP | valor real do dado | único estado vivo |
| Hindsight (self-hosted) | episódico "por quê" + sinônimo | recall 3-5s pós-tuning; 91,4% LongMemEval público |

Peças implantadas por cima (tudo reuso do orions-belt onde existia):

- **Corpus curado como fonte única**: 73 literais transcritos com arquivo:linha (gap→0),
  glossário unificado 171=171 com `search_aliases` fora da prosa, Vale gerado do glossário,
  catraca `check_regressao.py` no CI (lint 603 · glossário 237 · ident 0,944 · exact 0,978).
- **Roteador de contexto formal** (`context_routing.py`): 7→**9 métodos** — `episodic-memory`
  (stage 0, paralelo aos docs canônicos: F0.5 "memória roteia O QUE explorar") e
  `fazgraph-lineage` (LIVE_STATE: grafo ANTES do postgres, com aresta de dependência —
  doutrina virou grafo executável). Disponibilidade lida do registry
  (`context-sources.json`, provider hindsight com `evidence_class: hint_not_proof`), nunca de
  conf gerada por Copier. 54 testes, 0 FAIL; rota legada byte-idêntica com flags default.
- **Papéis escritos NAS skills** (exploration-protocol/context-delivery, 4 cópias) com teste
  anti-drift provado nos dois sentidos, e a regra imutável: *memória e grafo são DICA; prova é
  código (arquivo:linha) ou banco.*
- **Memória operável**: Hindsight consertado (pgvectorscale p/ 4096 dims dentro do volume;
  primária `deepseek-v4-flash-0731` via OpenRouter — zero tempestade 429; fallback z.ai
  5.3→5.2→5.1; reranker `cohere/rerank-4-pro` — recall 14,6-22,3s→**3,2-5,1s**), bank 100%
  taggeado (119→0 sem `source:*`, com guarda auto-tag anti-fricção), watchdog + dreno.
- **Invalidação bi-temporal on-merge** (princípio Graphiti portado, produto não instalado):
  poller LaunchAgent 15min sobre PRs MERGED dos 3 repos → join diff×`evidence-map.csv`
  (330 linhas doc→arquivo:ranges) com **anti-ruído por range de linha** → marca
  `stale_candidate:<pr>:<data>` **só nos índices** (evidence-map.state + fila append-only) —
  nunca no .md (medido: inserir 1 linha desloca o section-map e regride a catraca; o
  instrumento defendeu o corpus do próprio autor da feature).
- **Medição própria de memória**: mini-LongMemEval interno (30 perguntas, 5 categorias sobre
  fatos reais) — baseline 0,828; extração/multi-sessão/temporal = 1,00; **abstenção = 0,33**
  (a memória responde com confiança 0,77-0,95 sobre o que NÃO existe) — a fraqueza mais
  perigosa agora tem número e categoria.

## 4. Como opera no dia-a-dia (4 ciclos)

1. **Task-start (por prompt)**: hook `exploration-kickoff` injeta a rota F0→F5 lida do
   registry — F0 âncora verbatim (request-ledger) → **F0.5 recall/reflect da memória** →
   F1 docs canônicos → F2 código (CodeGraph/rg por task-shape) → F3 FazGraph→Postgres →
   F4 join → F5 docs oficiais. Cada método federado tem matcher e recibo no ledger.
2. **On-merge (15 min, zero tokens)**: `com.fazcapital.docs-onmerge` → poller → PRs MERGED →
   diff×evidence-map → docs stale marcadas nos índices + fila para o doc-fragility-loop.
   Backtest real: PR#262 tocou exatamente as linhas citadas por 3 docs de endpoint —
   11 hits, 0 falso-positivo duro.
3. **Memória (por sessão)**: captura automática no Stop (essência, não transcript); âncora
   intra-sessão continua sendo o request-ledger/reinject (compaction-proof). Correções viram
   docs "Correction:"; re-ingest por upsert limpa fatos velhos do mesmo doc.
4. **Medição (por mudança)**: prova de 204 perguntas (5s, determinística) + catraca no CI +
   mini-LongMemEval — toda melhoria de processo tem que mover um desses números ou é teatro.

## 5. KPIs — ganho provado × ganho a provar

Provados (antes→depois, mesma régua): contexto certo 0,144→0,978 · resposta existente 17/90→90/90 ·
retenção quebrada→fim-a-fim (240 docs) · recall 22s→3-5s · extração com perda→zero 429 ·
bank 51% sem tag→0% · doc stale manual→15min automático 0 FP · roteamento 0→9 métodos/54 testes.

A provar (instrumento pronto, gatilho definido): G1 NL MRR 0,624→≥0,75 IC95% (piloto na fila) ·
sobreposições <5/sem × 4 semanas (card FBI-3151) · "review de primeira" no próximo PR real ·
abstenção 0,33→calibrada.

## 6. Lições estruturais promovidas

1. **Instrumento antes de melhoria**: o harness de 204 perguntas achou os 73 gaps, derrubou a
   expansão ingênua e pegou o próprio autor 2× (banner que regrediu a catraca; restauração por
   regex imperfeita). Sem régua, tudo vira "acho que melhorou".
2. **Marcação vive em índice, não em prosa curada**: qualquer linha inserida num doc indexado
   por linha quebra o section-map; estado é dado, não texto.
3. **O gargalo não era falta de contexto — era ROTEAMENTO**: 12/17 achados de review tinham
   resposta escrita. F0.5 + papéis nas skills + recibos atacam exatamente isso.
4. **Memória é dica, nunca prova** — e ela não sabe dizer "não sei" (abstenção 0,33): claim
   derivado de memória reconfirma em código/DB antes de virar veredito.
5. **Curadoria automática exige modelo barato e destacado** (decisão do dono): o curador
   pré-compact ficou em backlog com contrato — haiku/luna/deepseek-flash + manifest provando
   modelo e custo, spawn `start_new_session`, nunca no caminho da sessão.

## 7. Ponteiros

- makershub: `tasks/spec-contexto-federado.md`, `tasks/plan-contexto-federado.md`,
  `.harness/runs/contexto-federado/RUN.md`, manifests `.harness/evidence/contexto-federado-*.json`,
  roteador `.harness/lib/context_routing.py` (+54 testes).
- fazgraph-canonical-v4: commits `34098d6..3c14b69` (história, literais, glossário, CI, spec,
  pilotos, onmerge, benchmarks); `_program/onmerge/` (poller/mark_stale/range_match/repo_map);
  `_program/benchmarks/mini-longmemeval-*`.
- Máquina: LaunchAgents `com.fazcapital.docs-onmerge` (900s) e `com.fazcapital.hindsight-watchdog`;
  `~/.hindsight/hindsight-makershub.env` (fonte de recriação); cards Jira FBI-3151/FBI-3152.
