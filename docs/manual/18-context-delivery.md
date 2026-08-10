# 18. Context Delivery e busca híbrida adaptativa

Ative com:

```bash
./harness-install.sh <alvo> --defaults \
  --data use_context_delivery=true \
  --data harness_context_provider=codegraph
```

Sem `use_context_delivery=true`, nenhum marker ou gate novo é gerado.

## Prefixo executável do Council

Novos runs mutáveis usam:

```text
ANCHOR -> CONTEXT-PLAN -> CONTEXT-DELIVERY -> PHASE-PLAN
```

`PHASE-PLAN` é recusado enquanto a entrega de contexto não tiver passado pelo schema e pela verificação de execução.

## Como o router decide

P1–P3 são calculados do Git; P4 é derivado do conjunto completo de definições `path:line` comprovadas por receipts; P5 vem de `codegraph status --json` executado pelo coordenador na mesma sessão; P6 vem do `task_shape`. Antes do primeiro diff, P1–P3 ficam `DEFERRED`.

| Forma da tarefa | Ordem obrigatória |
|---|---|
| `LEXICAL_ENUMERATION` | status preflight ∥ docs → `rg` → classificação/leitura → grafo ou LSP para reachability |
| `KNOWN_SYMBOL_IMPACT` de alto raio | docs → CodeGraph ∥ `rg` → join → P4 → LSP quando necessário |
| `KNOWN_SYMBOL_IMPACT` de baixo raio | consulta semântica principal → verificação focada |
| `DYNAMIC_STATE_FLOW` | `rg` → leitura/LSP do caminho local → grafo para consumidores externos |
| `DOCS_OR_CONFIG` | docs canônicos → busca textual → leitura |
| `LIVE_STATE` | estado read-only ∥ código relevante → reconciliação |

O router rejeita dependências declaradas como paralelas, recusa `parallel_shards` até existir proveniência por shard e impede que o modelo subestime o risco mínimo medido. `codegraph-status` é preflight separado no coordenador e anterior à consulta operacional do scout: o status prova frescor, não substitui `codegraph`/impact/search. A consulta operacional permanece uma evidência própria.

## Prova de execução

O hook `context-tool-ledger.py` registra chamadas reais do coordenador e das superfícies que o runtime expõe. No Codex, o receipt de status injeta o comando exato `codex_context_receipts.py --session-id ... --parent-transcript ...`; execute-o depois de `wait_agent`. Ele bloqueia transcript incompleto, modelo divergente, MCP sem `read_only_hint=true` e shell mutável. A entrega precisa vincular:

- `tool_use_id`;
- runtime, sessão, `agent_type` e modelo do scout;
- hash do input e do output;
- sequência Pre/Post;
- artefato JSON com os receipts exatos;
- lifecycle do subagent;
- freshness real do provider pela CLI do coordenador, aceita somente como `codegraph-status`;
- cobertura por identidades e claims auditáveis.

Hash de arquivo isolado não basta. Freshness autodeclarada não basta. Texto dizendo “usei CodeGraph” não basta.

## Agentes e configuração

- Claude Code: `.claude/agents/<project>-context-{scout,shard}.md`.
- Codex: `.codex/agents/<project>-context-{scout,shard}.toml`.
- Claude Code usa `.mcp.json` do projeto para CodeGraph.
- Codex usa `[mcp_servers.codegraph]` em `.codex/config.toml`.
- `[agents]` usa `max_concurrent_threads_per_session`; o harness não emite `max_depth` sem suporte oficial comprovado.
- Modelos e efforts dos quatro workers são respostas do Copier; os shards são gerados, mas o router os bloqueia enquanto faltar enforcement de receipts por shard.

## Testes

```bash
bash templates/tests/test_context_delivery_regression.sh
bash templates/tests/test_council_rendered_runtime.sh
python3 engine/release_check.py
```

Smokes opcionais/ambientais:

```bash
bash templates/tests/test_context_delivery_config_smoke.sh
bash templates/tests/test_context_delivery_provider_smoke.sh
ORIONS_RUNTIME_SMOKE=1 bash templates/tests/test_context_delivery_runtime_smoke.sh
```

O runtime smoke prova:

1. TOML Codex sozinho não registra agent no Claude;
2. Markdown Claude gera lifecycle real;
3. Codex delega ao papel configurado e vincula lifecycle, modelo e tools ao transcript real concluído;
4. os hosts reais conseguem consumir a configuração instalada.

O provider probe direto usa o handshake MCP stdio legado `2025-11-25` para a consulta operacional e a CLI JSON para o status; ele não substitui os smokes dos hosts.

## Política de commit

O aplicador do pacote só cria commit após:

- overlay e schemas válidos;
- testes de regressão renderizados;
- Council runtime tests;
- `engine/release_check.py` integral;
- `git diff --check`;
- runtime smoke real, ou override explícito `ALLOW_RUNTIME_SMOKE_SKIP=1` registrado no relatório.

`SKIP` nunca é contado como `PASS`.
