# SCHEMA.md — como este repositório é organizado

> Padrão: **Karpathy LLM Wiki**, aplicado ao repositório `orions-belt` inteiro. Esta é a constituição do framework — e é dogfooding deliberado: o mesmo sistema de curadoria documental que o framework INSTALA nos projetos-alvo (capítulo 10 do manual, `docs/manual/10-wiki-karpathy.md`) governa o próprio repositório do framework.

## 0. Objetivo

Uma LLM (ou um humano) que chega neste repositório tem UMA de três perguntas — "o que é este harness e como cada componente funciona?", "como instalo num projeto?", ou "por que foi construído assim?" — e cada pergunta tem resposta em um lugar diferente. Este documento e o `llms.txt` existem para a pergunta certa levar direto ao lugar certo, sem ler o repositório inteiro.

## 1. Três audiências, três lugares, zero sobreposição

| Audiência | Pergunta | Onde | Conteúdo |
|---|---|---|---|
| **Usuário do produto** | "Quero ENTENDER o harness e configurar cada componente" | [`docs/manual/`](docs/manual/README.md) | A documentação canônica: 15 capítulos genéricos, cada um citando as variáveis da config central pelo nome e linkando os arquivos reais do framework. |
| **Instalador** | "Quero instalar num projeto" | [`templates/`](templates/) + [`copier.yml`](copier.yml) | A árvore Copier parametrizada — o que É instalado. Procedimento: capítulo 14 do manual. |
| **Arquiteto/mantenedor** | "Qual é a arquitetura atual/alvo e quais contratos governam a evolução?" | [`docs/architecture/`](docs/architecture/README.md) | Arquitetura canônica, estado atual versus alvo, trust boundaries e sequência de adoção. |
| **Arqueólogo** | "Por que foi desenhado assim?" | [`docs/planning/`](docs/planning/) | História da construção. Não é produto — a verdade ATUAL é código + arquitetura/manual. |

Infraestrutura de suporte (serve as três audiências, não é uma quarta): `engine/` (lints + contrato executável, compartilhados entre o repo do framework e os projetos-alvo) e `.claude-plugin/` (reservado, fase F6).

## 2. Naming

- Índices de roteamento da raiz: `llms.txt`, `README.md`, `SCHEMA.md` (este arquivo).
- `docs/manual/`: classe **sequenced** — `NN-slug.md`, kebab-case, ordem de leitura sugerida; índice próprio em `docs/manual/README.md`.
- `docs/architecture/`: documentos **living** de arquitetura, indexados por `docs/architecture/README.md`.
- `docs/planning/`: `00-plano-consolidado.md` + `research/NN-slug.md` (sequenced) + notas **living** de fase (`notas-f*.md`, sem data, editadas in-place).
- `docs/log.md`: índice temporal único do repositório (formato `## [YYYY-MM-DD] tipo · tópico`, mais recente primeiro).
- `templates/`: naming ditado pelo Copier (`*.jinja`, diretórios/arquivos condicionais `{% if var %}...{% endif %}`) — não é Karpathy, é a convenção da ferramenta de scaffolding.

## 3. Regras de manutenção (enforced pelo próprio motor)

O lint que o framework instala nos projetos-alvo roda AQUI também: `python3 engine/lint/docs_wiki_lint.py --worktree`. As regras que ele cobra neste repo:

- **Doc novo/renomeado/removido sob `docs/` exige, no MESMO diff:** entrada no `docs/log.md` + atualização do índice da categoria (`docs/manual/README.md` para capítulos do manual). Indexação não é tarefa para depois; é parte da mudança.
- **Órfão é FAIL:** todo arquivo sob `docs/` precisa estar mencionado em algum índice/log/README.
- **Integridade referencial em rename/delete:** `python3 engine/lint/ref_integrity.py --staged` (também no pre-commit) — links markdown mortos e citações vivas a paths antigos, com allowlist para placeholders ilustrativos em `.ref-integrity-allowlist`.

## 4. Roteamento (a regra de ouro para uma LLM)

1. Leia `llms.txt` (ou este SCHEMA.md se a pergunta é sobre a ORGANIZAÇÃO do repo).
2. Comportamento/configuração de um componente → `docs/manual/` (o README do manual roteia por capítulo). Instalação → capítulo 14 + `copier.yml`. Razão histórica de uma decisão → `docs/planning/` (comece pelo plano; os relatórios de research só quando o plano apontar).
3. Conflito entre manual e planning → o manual (+ o código em `templates/`/`engine/`) é a verdade atual; planning é registro de época e não é atualizado retroativamente.

### Precedência entre os dois `SCHEMA.md`

Este `SCHEMA.md` da raiz é a constituição do **repositório do framework** e tem precedência aqui.
`docs/SCHEMA.md` é o seed dogfood da política de wiki que o Orion instala em projetos-alvo; dentro
deste repositório ele é subordinado a este arquivo. Em um projeto instalado que não tenha uma
constituição raiz própria, `docs/SCHEMA.md` governa a wiki. Se o projeto já tiver uma constituição
raiz, ela prevalece e o seed deve ser adaptado sem alegar autoridade concorrente.

## 5. Ciclo de manutenção deste nível (raiz)

- **Fase do WBS concluída** → atualizar a seção "Estado" do `README.md` + entrada no `docs/log.md`.
- **Componente novo/alterado em `templates/` ou `engine/`** → refletir no capítulo correspondente do manual no mesmo ciclo (o manual descreve o que o framework INSTALA; template e manual driftados = bug de documentação). Limitação nova ou resolvida → `docs/manual/15-limitacoes-conhecidas.md` (living).
- **Capítulo novo no manual** → linha na tabela do `docs/manual/README.md` + entrada no `docs/log.md` (o lint cobra os dois) + atualizar a lista de capítulos no `llms.txt` se a estrutura mudar.
