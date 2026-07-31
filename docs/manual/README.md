# Manual do Orion's Belt

**A documentação canônica do produto**: o que o framework instala num projeto, como cada componente funciona, quais variáveis da config central o governam e como instalar/atualizar. Todo capítulo referencia os arquivos REAIS do framework (em `templates/`, `engine/`, `copier.yml`) e as variáveis pelo nome (`HARNESS_*`, `PROD_*`, `PROJECT_NAME`) — nunca valores fixos de um projeto específico.

Convenções: capítulos são classe **sequenced** (`NN-slug.md`, ordem de leitura sugerida — mas cada um se lê sozinho); fluxogramas em blocos ` ```mermaid ` (retângulo = ação, losango = decisão); cada componente segue a didática *o que é / quando dispara / o que faz / fluxograma / como configurar*. A história de COMO o framework foi construído não está aqui — está em [`docs/planning/`](../planning/00-plano-consolidado.md).

## Capítulos

| # | Capítulo | Leia quando |
|---|----------|-------------|
| 01 | [Visão geral: o harness, as 3 camadas e o ciclo de vida de um turno](01-visao-geral.md) | Precisa do mapa: eventos de hook, config central, tabela evento→script |
| 02 | [Hooks de início de sessão: dev-doctor, git-doctor, lessons-inject, marathon-reinject](02-hooks-sessionstart.md) | Entender o contexto que aparece "de graça" quando a sessão abre |
| 03 | [Hooks de cada prompt: lei-zero-kickoff e understand-context-inject](03-hooks-prompt.md) | Entender injeção condicional de regra por assunto do prompt |
| 04 | [Hooks antes de cada ferramenta: o semáforo de subagents e o guard de diff](04-hooks-pretooluse.md) | Entender bloqueio pré-execução; configurar o cap de subagents |
| 05 | [Hooks depois de cada edição: ds-gate e deliverable-scrub-gate](05-hooks-posttooluse.md) | Entender os gates de qualidade com feedback no mesmo turno |
| 06 | [Os porteiros do fim de turno: completion-gate, ui-evidence-gate, marathon-stop-gate, reap-leaks](06-stop-gates.md) | Entender por que o turno foi bloqueado ao terminar; os escape hatches |
| 07 | [Regras hookify: guardas declarativas em markdown](07-hookify.md) | Criar/entender uma guarda sem escrever código; os guardas de produção |
| 08 | [Execuções longas: marathon, estado durável e o loop de manutenção](08-marathon-e-loops.md) | Execução multi-fase que sobrevive a compactação e não é abandonada |
| 09 | [Skills operacionais: os manuais de procedimento](09-skills-operacionais.md) | Entender o que é uma skill, os pares gate+skill e as skills do núcleo |
| 10 | [A wiki Karpathy: documentação com indexação temporal e lint](10-wiki-karpathy.md) | Organizar docs; naming por classe temporal; docs-wiki-lint e ref-integrity |
| 11 | [O council e os subagents: revisão adversarial](11-council-subagents.md) | Orquestrar subagents; os loops adversariais; witness e ledger |
| 12 | [O ciclo de auto-melhoria: lessons.md e promoção a regra](12-auto-melhoria.md) | Fazer o agente aprender com erros entre sessões |
| 13 | [Understand Anything: grafo de código em monorepo e o diff relativo](13-understand-anything.md) | Projetos com grafo de código cuja raiz é subdiretório do monorepo |
| 14 | [Instalação e atualização: copier copy, harness-init e copier update](14-instalacao-e-update.md) | Instalar o framework num projeto; adaptar à stack; atualizar sem perder edições |
| 15 | [Apêndice: limitações conhecidas](15-limitacoes-conhecidas.md) | O que o framework NÃO cobre hoje; contratos que o projeto preenche |
| 16 | [Grafo de decisão de ferramentas de contexto (blast radius)](16-grafo-contexto.md) | Roteamento determinístico entre grafo de código, grep e LSP antes de mudar símbolo compartilhado; guardas hookify de núcleo e de contrato de dados |
| 17 | [Protocolo de exploração (task-start), gate de clarificação e gate de push](17-protocolo-exploracao.md) | Por onde a leitura COMEÇA (antes do capítulo 16); exigir o contrato de decisão carregado antes de perguntar ao humano; rodar a suite antes do push |

## Roteamento para LLMs

Índice de roteamento do repositório inteiro (padrão llms.txt): [`llms.txt` na raiz](../../llms.txt). Regra: instalar → capítulo 14 + `copier.yml`; entender um componente → capítulo do evento correspondente (02-06) ou do subsistema (07-13); decidir se o framework serve → capítulo 01 + 15.
