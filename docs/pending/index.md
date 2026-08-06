<!-- GERADO por engine/lint/pending_index.py — NAO EDITE A MAO.
     A fonte de cada item e o arquivo docs/pending/<id>.md correspondente.
     Regenere com: python3 engine/lint/pending_index.py -->

# Pendencias abertas

**2 itens abertos** — 1 esperam decisao do dono, 1 sao trabalho de agente. Resolver um item e **apagar o arquivo** `docs/pending/<id>.md` e regenerar este indice; o git guarda o historico.

Cada item declara a `fonte` que o originou e a `citacao` textual dela. `pending_index.py --check` confere que a citacao ainda existe — item cujo ponteiro apodreceu vira **re-auditoria**, nunca afirmacao.

## Espera o dono

_decisao humana: preferencia, escopo, emenda de lei, custo._

| | item | severidade | bloqueia | fonte |
|---|---|---|---|---|
| [ ] | [Migração dos tokens de contrato PT→EN precisa de janela de alias antes de entrar](migracao-tokens-en-precisa-janela-de-alias.md) | alta | adocao da branch feat/en-tokens-and-docs-sync (10 commits, nunca pushada) | [`engine/contract/scripts/agent_swarm_ledger.py:102`](../../engine/contract/scripts/agent_swarm_ledger.py) |

## Trabalho de agente

_resolvivel com codigo, medicao ou leitura — nao pergunte, faca._

| | item | severidade | bloqueia | fonte |
|---|---|---|---|---|
| [ ] | [O guard de pares coloridos resolve por RANK; a lei exige ENTIDADE na cabeça](guard-de-pares-nao-conhece-entidade-so-rank.md) | media | conformidade total do ds-gate com a GRAMMAR do ui-tokenizer-v2 | [`templates/tests/test_ds_pairs_oklch.sh:86`](../../templates/tests/test_ds_pairs_oklch.sh) |
