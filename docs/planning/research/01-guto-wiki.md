# Investigação 1 — `guto-wiki` (github.com/gutocarollo/guto-wiki)

> Clone lido integralmente em
> `/tmp/claude-1000/-home-augusto-code-learnhouse/d14a153c-a4e0-4575-82ab-a19228a1a393/scratchpad/harness-portable/clones/guto-wiki`
> (27 arquivos de conteúdo, excluindo `.git/`). Todos os 27 foram lidos byte-a-byte com a ferramenta
> `Read` (não há achado por amostragem ou grep isolado nesta seção). Comparações contra o repo local usam
> `diff`/`Read` reais, não memória.
>
> Nota crítica de partida: o capítulo 14 do `harness-wiki` local
> (`/home/augusto/code/harness-wiki/chapters/14-repos-publicos.md`, Linha 81) **declara explicitamente que
> não leu o conteúdo interno dos arquivos** do `guto-wiki` — só README + 1 listagem de diretório. Esta
> investigação é a primeira leitura profunda de fato.

---

## Sumário executivo

`guto-wiki` é um repositório público de **duas camadas sobrepostas**:

1. **Governança do próprio repo público** (raiz): `index.md` + `log.md` + `wiki-tooling.conf` +
   `scripts/wiki-lint.py` + CI + pre-commit — um wiki Karpathy funcionando ao vivo, versão mínima.
2. **Um "kit de instalação" sanitizado** (`padronizacao-documentacao/artefatos/`): 18 arquivos que são a
   generalização/parametrização do harness real do `learnhouse`, prontos para copiar em outro repositório.
   Este kit é o artefato relevante para o framework portátil que estamos planejando — é **quase idêntico**
   ao que já existe em `/home/augusto/code/learnhouse/{scripts,docs,.claude,tasks,.githooks}`, mas com uma
   diferença estrutural decisiva: **todo path hardcoded no learnhouse foi extraído para uma única fonte de
   configuração, `docs-tooling.conf`** (formato `KEY=value`), e os scripts/skills foram reescritos para
   LER essa config em vez de embutir o path.

Achado mais importante para o plano: **o `docs-wiki-lint.py` e o `ref-integrity.py` locais do learnhouse
já são o "core" certo — só faltam ~30 linhas de `load_config()` e 3 flags de CLI (`--worktree/--staged/
--diff-base`) que a versão pública já tem prontas.** Não é preciso reescrever nada do zero; é portar um
diff pequeno e concreto (detalhado na seção b).

---

## (a) Inventário completo — os 27 arquivos

### Raiz do repo (governança do `guto-wiki` como wiki pública)

| Arquivo | Propósito |
|---|---|
| `README.md` | Landing page do repo. Explica o padrão Karpathy (dupla indexação), aponta para `wiki-tooling.conf`, lista os 4 pré-requisitos práticos de "como preparar um projeto para IA" (config central, wiki temporal, grafo Understand Anything opcional, gates locais/remotos). |
| `index.md` | Catálogo por tópico com 2 categorias: `padronizacao-documentacao` (o conteúdo) e `governanca-da-wiki` (a meta-governança do próprio repo: lint, conf, CI, pre-commit, gitignore). |
| `log.md` | Cronológico append-only, 4 entradas (`2026-07-07` bootstrap + pacote; `2026-07-08` ×2 melhorias). Formato `## [YYYY-MM-DD] tipo · tópico — resumo`. |
| `wiki-tooling.conf` | Config central **deste repo específico** (não o pacote portável — ver `docs-tooling.conf` abaixo). 8 chaves: `WIKI_INDEX`, `WIKI_LOG`, `WIKI_LINT`, `PACKAGE_ROOT`, `PACKAGE_SCHEMA`, `PACKAGE_DOCS_LINT`, `PACKAGE_REF_INTEGRITY`, `UNDERSTAND_*` (5 chaves), `IGNORED_TOOL_DIRS`. |
| `.gitignore` | Ignora `.understand-anything/`, `**/.understand-anything/`, caches Python (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`). |
| `.pre-commit-config.yaml` | 2 hooks locais: `guto-wiki-lint-staged` (`wiki-lint.py --staged`) e `guto-wiki-lint-global` (`wiki-lint.py` sem args). |
| `.github/workflows/wiki-integrity.yml` | CI: lint global sempre + lint diff-aware (`--diff-base` contra `pull_request.base.sha` ou `event.before`), com `fetch-depth: 0`. |
| `scripts/wiki-lint.py` | Lint ativo **desta wiki específica** (272 linhas) — versão standalone, não a versão repo-wide genérica (essa está em `artefatos/scripts/docs-wiki-lint.py`). Ver detalhamento em (b). |

### `padronizacao-documentacao/` (o conteúdo — não-estrutural, documenta a metodologia)

| Arquivo | Propósito |
|---|---|
| `2026-07-07-apanhado-padronizacao-documentacao.md` | **Documento mais denso do repo** (136 linhas). Narra por que o padrão existe (2 incidentes-gatilho: artefato de 10MB que matou uma sessão + 38 refs quebradas por rename sem detector), cronologia dia-a-dia do que foi construído, mapa dos 18 artefatos, uma seção de **convergência independente** comparando a trilha "Codex" vs a trilha "Claude" no repo de origem (tabela de 9 dimensões: link morto, citação a nome antigo, falso-positivo em fence, unquote de `%20`, `check_no_foreign_live_links`, CI, autoteste, semântica staged/working-tree, arquitetura), e um roteiro §6 de **"como portar para um repositório novo"** em 9 passos — este roteiro é essencialmente o esqueleto do plano que estamos construindo. |
| `artefatos/README.md` | Mapa tabular dos 18 artefatos: arquivo → destino sugerido → papel. É o índice do kit de instalação. |
| `artefatos/docs-tooling.conf` | **A peça central do kit portável.** Ver (b). |
| `artefatos/docs/SCHEMA.md` | Constituição parametrizada (114 linhas) — a versão genérica do `docs/SCHEMA.md` local, referenciando `docs-tooling.conf` por chave em vez de hardcode. |
| `artefatos/githooks/pre-commit` | Adaptador fino: `exec python3 .../scripts/ref-integrity.py --staged`. Byte-a-byte **idêntico** ao local `/home/augusto/code/learnhouse/.githooks/pre-commit`. |
| `artefatos/github-workflows/docs-integrity.yaml` | CI parametrizado — quase idêntico ao `docs-integrity.yaml` local, mas com 3 diferenças (ver seção c). |
| `artefatos/hooks/lessons-inject.sh` | Hook `SessionStart` — injeta `tasks/lessons.md` (cap 80 linhas) no contexto. |
| `artefatos/loop.md` | Loop de manutenção genérico (6 checks) — versão parametrizada do `.claude/loop.md` local (usa `SPECIALIZED_GATE_CMD`/`SPECIALIZED_MINING_*` em vez de paths `apps/web/scripts/ds-gate.sh` hardcoded). |
| `artefatos/pre-commit-config.yaml` | 3 hooks (vs 2 do `wiki-tooling` da raiz): `docs-wiki-lint-staged`, `docs-wiki-lint-global`, `ref-integrity-staged`. |
| `artefatos/ref-integrity-allowlist` | Allowlist sanitizada — nomes de projeto trocados por placeholders (`proposta-comercial-<account>.pdf` em vez do nome real do cliente). |
| `artefatos/scripts/docs-wiki-lint.py` | **Lint canônico repo-wide, versão pública** — superset do `scripts/docs-wiki-lint.py` local. Ver (b). |
| `artefatos/scripts/ref-integrity.py` | Integridade referencial git-aware — quase idêntico ao `scripts/ref-integrity.py` local, +30 linhas de `load_config()`. Ver (b). |
| `artefatos/scripts/scope-wiki-lint.py` | Shim de compatibilidade **genérico** (lê `LEGACY_WIKI_SCOPE` do config) — o local equivalente (`design-system-wiki-lint.py`) tem o scope `"design-system"` hardcoded em vez de ler de config. |
| `artefatos/skills/adversarial-review/SKILL.md` | Contrato de review adversarial parametrizado — usa `ARCHITECTURE_*`/`SPECIALIZED_*`/`CODE_ROOTS` de `docs-tooling.conf` em vez de paths fixos do learnhouse. 226 linhas, taxonomia de 9 classes de prova (PLANO/ESCOPO, ARQUITETURA, UI/ESPECIALIZADO, CODIGO/LOGICA, DADO/DB, PERFORMANCE, SEGURANCA, FONTE/OSS, TESTE/EVIDENCIA). |
| `artefatos/skills/delivery-council/SKILL.md` | Council genérico (245 linhas) — mesma arquitetura do `learnhouse-delivery-council` local (Planning/Execution Adversarial Loop, `START_AT`, `AUTO_DECIDE`), mas nomes de subagent vêm de chaves (`ADVERSARIAL_REVIEWER_AGENT`, `CONTEXT_SCOUT_AGENT`, `IMPLEMENTER_AGENT`, `TEST_AUDITOR_AGENT`) em vez de `learnhouse-context-scout`/`learnhouse-implementer`/etc. |
| `artefatos/skills/ref-integrity/SKILL.md` | Skill invocável (57 linhas) — quase idêntica à local, referencia `docs-tooling.conf` para `REF_INTEGRITY_ARCHIVE_PREFIXES`/`IGNORED_TOOL_DIRS`. |
| `artefatos/skills/repo-wiki-curator/SKILL.md` | Skill orquestradora (67 linhas) — idêntica em estrutura à local, com `SPECIALIZED_SCHEMA` no lugar de `docs/design-system/SCHEMA.md` hardcoded. |
| `artefatos/tasks/lessons.md` | 7 lições reais copiadas do learnhouse (datas 2026-07-07), sanitizadas. Duas já marcadas `[PROMOVIDA → ...]`. |
| `artefatos/CLAUDE.md` | CLAUDE.md curado (187 linhas) — recorte de METODOLOGIA apenas: blocos "Repo Wiki/Karpathy", "Repo-native Delivery Council", §0 LEI ZERO, §14 DRY, §15 Boris Cherny, §16 self-improvement. Sem blocos de infra/produção/design-system/credenciais. |

---

## (b) O padrão `.conf` — formato exato, variáveis, e quem consome

### Formato

Nos dois arquivos (`wiki-tooling.conf` da raiz e `padronizacao-documentacao/artefatos/docs-tooling.conf`):

```
KEY=value
# comentário com '#'
```

- Uma chave por linha, sem seções (`[section]`), sem aspas, sem tipos — tudo string.
- Caminhos relativos à raiz do repositório.
- CSV inline para listas: `IGNORED_TOOL_DIRS=.understand-anything,.anythingllm,__pycache__,...` — o
  parser faz `.split(",")` e `.strip()` por item.
- Comentário de linha inteira ou trailing (`line.split("#", 1)[0].strip()`).
- **Sem seções, sem nesting, sem tipo, sem valor default no arquivo** — todo default fica hardcoded no
  Python que consome (`config_csv(key, default=set(...))`).

### As duas variantes existem por motivo diferente

1. **`wiki-tooling.conf`** (raiz, 26 linhas) — config do **repositório guto-wiki em si** (uma wiki pública
   mínima, sem código de produto). Chaves: `WIKI_INDEX`, `WIKI_LOG`, `WIKI_LINT`, `PACKAGE_ROOT`,
   `PACKAGE_SCHEMA`, `PACKAGE_DOCS_LINT`, `PACKAGE_REF_INTEGRITY`, `UNDERSTAND_PROJECT_ROOT`,
   `UNDERSTAND_GRAPH_DIR`, `UNDERSTAND_KNOWLEDGE_GRAPH`, `UNDERSTAND_INCREMENTAL_DOC` (vazio),
   `UNDERSTAND_INCREMENTAL_SKILL` (vazio), `UNDERSTAND_CHANGED_FILES_CMD=git diff --name-only <base>..HEAD`
   (genérico, sem `--relative`), `IGNORED_TOOL_DIRS`.

2. **`docs-tooling.conf`** (dentro de `artefatos/`, 58 linhas) — o **template para portar a governança
   documental a um repo destino QUALQUER**, com comentário explícito na Linha 3: *"Copie para a raiz do
   repo destino como `docs-tooling.conf`"*. Tem 4 blocos de chaves que `wiki-tooling.conf` não tem:
   - `DOCS_ROOT`/`DOCS_INDEX`/`DOCS_LOG`/`DOCS_SCHEMA`/`DOCS_WIKI_LINT`/`SCOPE_WIKI_LINT`/
     `REF_INTEGRITY`/`REF_INTEGRITY_ALLOWLIST`/`REF_INTEGRITY_ARCHIVE_PREFIXES` (Linhas 6-14)
   - `GITHOOKS_PRE_COMMIT`/`PRE_COMMIT_CONFIG`/`DOCS_CI_WORKFLOW`/`LOOP_DOC`/`LESSONS_FILE` (Linhas 16-20)
   - **"Project-specific paths"** (Linhas 22-36): `PROJECT_ROOT`, `CODE_ROOTS=apps/api,apps/web,packages,
     migrations,scripts,tests`, `ARCHITECTURE_DOCS`, `ARCHITECTURE_INDEX`, `SPECIALIZED_DOCS`,
     `SPECIALIZED_INDEX`, `SPECIALIZED_SCHEMA`, `SPECIALIZED_TOKEN_SOURCE=apps/web/styles/globals.css`,
     `SPECIALIZED_UI_COMPONENTS=apps/web/components/ui`, `SPECIALIZED_GATE_CMD=bash apps/web/scripts/
     ds-gate.sh`, `SPECIALIZED_MINING_CHECK_CMD`, `SPECIALIZED_MINING_REGEN_CMD`,
     `SPECIALIZED_MINING_INGEST_CMD`, `LEGACY_WIKI_SCOPE=design-system` — **estes valores de exemplo são
     literalmente os paths REAIS do learnhouse** (`apps/web/styles/globals.css`,
     `apps/web/scripts/ds-gate.sh`), confirmando que este `.conf` foi extraído diretamente do repo privado
     e não generalizado a ponto de perder a referência de origem.
   - `DELIVERY_COUNCIL_SKILL`/`ADVERSARIAL_REVIEW_SKILL`/`CLARIFICATION_PLAN_SKILL`/`CONTEXT_SCOUT_AGENT`/
     `IMPLEMENTER_AGENT`/`ADVERSARIAL_REVIEWER_AGENT`/`TEST_AUDITOR_AGENT` (Linhas 39-45) — nomes de
     skill/subagent parametrizados.
   - `UNDERSTAND_*` (Linhas 49-58) — aqui SIM aparece a versão avançada:
     `UNDERSTAND_PROJECT_ROOT=apps`, `UNDERSTAND_GRAPH_DIR=apps/.understand-anything`,
     `UNDERSTAND_CHANGED_FILES_CMD=git diff --relative=apps <last>..HEAD --name-only -- apps` (Linha 54)
     — **isto é exatamente a regra canônica do `CLAUDE.md` local** ("Understand Anything em apps/ = diff
     relativo obrigatório"), portada para dentro do `.conf` como comando parametrizável em vez de bloco
     de prosa fixo no CLAUDE.md.
     `UNDERSTAND_BATCH_INPUT_PATH_STYLE=relative-to-understand-project-root` (Linha 55) é uma chave nova
     sem equivalente local — documenta explicitamente a convenção de path que hoje só existe implícita no
     CLAUDE.md local.

### Como os scripts carregam o `.conf` (leitura real do código)

Ambos os scripts (`scripts/wiki-lint.py` Linhas 22-32 e `artefatos/scripts/docs-wiki-lint.py`
Linhas 31-43) implementam o **mesmo padrão de parser, sem biblioteca externa** (nem `configparser`, nem
`python-dotenv`):

```python
# artefatos/scripts/docs-wiki-lint.py L31-43
def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / "docs-tooling.conf", ROOT / ".docs-tooling.conf", ROOT / "wiki-tooling.conf"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        break
    return values
```

Pontos técnicos decisivos:

1. **Fallback em cadeia de 3 nomes de arquivo**: `docs-tooling.conf` → `.docs-tooling.conf` (dotfile) →
   `wiki-tooling.conf` — o primeiro que existir "vence" (`break` ao final do primeiro loop bem-sucedido).
   Isso é o que permite o MESMO script (`artefatos/scripts/docs-wiki-lint.py`) rodar tanto dentro do
   `guto-wiki` (usa `wiki-tooling.conf`) quanto em qualquer repo destino que adote `docs-tooling.conf`.
2. **`config_csv(key, default)`** (Linhas 49-53) é o helper para listas: se a chave não existir no
   `.conf`, retorna o `default` hardcoded no Python; se existir, faz split por vírgula. Isso é usado para
   `IGNORED_TOOL_DIRS` em `docs-wiki-lint.py`, `ref-integrity.py` (`ARCHIVE_PREFIXES`, `ARCHIVE_CONTAINS`)
   e `wiki-lint.py` local (`IGNORED_PARTS`).
3. **`DOCS = ROOT / CONF.get("DOCS_ROOT", "docs")`** (docs-wiki-lint.py L56) — único ponto de path
   configurável de fato: se `DOCS_ROOT` não estiver setado, cai em `"docs"` (comportamento idêntico ao
   local). Isso é o gancho que tornaria o lint aplicável a um repo com `documentation/` em vez de `docs/`
   sem tocar o script.
4. **`ref-integrity.py`** (Linhas 76-92) usa a MESMA função `load_config()`, mas com uma pequena
   diferença de implementação: usa `open()`/`os.path` em vez de `pathlib.Path.read_text()` (o resto do
   script é `pathlib`-free, usa `os.path` e `subprocess` puro) — inconsistência estilística menor entre os
   3 scripts, não funcional.
5. **`scope-wiki-lint.py`** (shim, 41 linhas) é o único consumidor de `LEGACY_WIKI_SCOPE`:
   `scope = load_config().get("LEGACY_WIKI_SCOPE", "specialized")` — repassa como
   `--scope <valor>` para `docs-wiki-lint.py`.

### Comparação direta: o que a versão pública parametrizou que a local hardcoda

Rodei `diff` real entre os pares equivalentes. Achados linha-a-linha:

| Script local (learnhouse) | Script público (guto-wiki `artefatos/`) | Diferença exata |
|---|---|---|
| `/home/augusto/code/learnhouse/scripts/docs-wiki-lint.py` (166 linhas, **sem** `load_config`) | `padronizacao-documentacao/artefatos/scripts/docs-wiki-lint.py` (312 linhas) | Local: `DOCS = ROOT / "docs"` hardcoded (Linha 24); `IGNORED_DIRS = {".understand-anything"}` hardcoded (Linha 29); **nenhuma** flag `--worktree`/`--staged`/`--diff-base` (`main()` só aceita `--scope`/`--strict-naming`, Linhas 107-113); **sem** `check_log_format`, `check_frontmatter_updated`, `check_stray_tool_tags`, `check_diff_policy`. Público: adiciona `load_config()`+`config_csv()` (Linhas 31-53), `DOCS = ROOT / CONF.get("DOCS_ROOT", "docs")` (Linha 56), `IGNORED_DIRS = config_csv(...)` (Linha 61), as 3 flags de diff-aware (Linhas 248-250) + `git_diff_name_status`/`check_diff_policy` (Linhas 183-229), e as 3 checagens novas (log format temporal decrescente, frontmatter `updated: YYYY-MM-DD`, tags de ferramenta soltas tipo o fechamento de tag de invocação de ferramenta grudado em markdown, regex `STRAY_TOOL_RE`, Linha 68). |
| `/home/augusto/code/learnhouse/scripts/ref-integrity.py` | `padronizacao-documentacao/artefatos/scripts/ref-integrity.py` | `diff` real (rodado nesta sessão) mostra só 2 blocos: (1) comentário de docstring Linha 21 troca `apps/.understand-anything/` (path real do learnhouse) por `.understand-anything/` genérico; (2) bloco novo de 30 linhas (`load_config`+`config_csv`, correspondendo às Linhas 76-105 do público) que substitui a constante fixa `is_archive` local (`return p.startswith("docs/_arquivo/") or ".understand-anything" in p or "/.trash-" in p`, Linha 91 local) por `ARCHIVE_PREFIXES`/`ARCHIVE_CONTAINS` carregados do `.conf` via `config_csv("REF_INTEGRITY_ARCHIVE_PREFIXES", ...)` e `config_csv("IGNORED_TOOL_DIRS", ...)`. **Toda a lógica de negócio (checks A/B, fence-blanking, stale-citation, `--selftest`) é byte-idêntica** — confirma que o `ref-integrity.py` local já está "pronto" para virar o script portável; falta só esse bloco de config. |
| `/home/augusto/code/learnhouse/scripts/design-system-wiki-lint.py` (shim com `"design-system"` hardcoded na chamada, Linha 18) | `padronizacao-documentacao/artefatos/scripts/scope-wiki-lint.py` | Público lê `LEGACY_WIKI_SCOPE` do `.conf` (default `"specialized"`) em vez de hardcodar `"design-system"` na chamada Python. |
| **inexistente localmente** | `wiki-tooling.conf` / `docs-tooling.conf` | Não há NENHUM arquivo `.conf` no learnhouse hoje (`find` confirmou 0 resultados) — toda configuração de path vive espalhada em prosa dentro de `.claude/CLAUDE.md`, `.claude/loop.md`, nos próprios scripts, e nas SKILL.md. Este é o gap estrutural nº 1 do plano. |
| `/home/augusto/code/learnhouse/.claude/loop.md` (Linhas 12, 15) hardcoda `apps/web/scripts/ds-classname-workflow-check.sh`, `apps/web/scripts/classname-miner-v2.mjs`, `apps/web/scripts/ds-gate.sh` | `padronizacao-documentacao/artefatos/loop.md` (Linhas 15, 20) | Público substitui os 3 comandos fixos por `SPECIALIZED_MINING_CHECK_CMD`/`SPECIALIZED_MINING_REGEN_CMD`/`SPECIALIZED_MINING_INGEST_CMD`/`SPECIALIZED_GATE_CMD` lidos de `docs-tooling.conf` — mesma estrutura de 6 checks, só o passo 3 e 5 tornam-se indireção por chave. |
| `/home/augusto/code/learnhouse/.ref-integrity-allowlist` cita `Proposta-Comercial-Quero-Quero.pdf` (nome real do cliente) | `padronizacao-documentacao/artefatos/ref-integrity-allowlist` | Público substitui por `proposta-comercial-<account>.pdf` — placeholder, não path funcional (o consumo real desse allowlist é por igualdade de string exata; o placeholder é só documentação do padrão, teria que ser reescrito por projeto). |
| skills locais nomeadas por projeto: `learnhouse-delivery-council`, `learnhouse-context-scout`, `learnhouse-implementer`, `learnhouse-adversarial-reviewer`, `learnhouse-test-auditor` (`.codex/agents/*.toml`, `.agents/skills/learnhouse-delivery-council/`) | `artefatos/skills/delivery-council/SKILL.md` usa `ADVERSARIAL_REVIEWER_AGENT`/`CONTEXT_SCOUT_AGENT`/`IMPLEMENTER_AGENT`/`TEST_AUDITOR_AGENT` como INDIREÇÃO de nome | O público não hardcoda `learnhouse-*`; o nome do subagent é uma chave do `.conf`. Isso é preservado como *padrão a adotar*, não como arquivo 1:1 — a skill local precisaria ser reescrita para ler o nome do agente de uma config, ou o framework portátil precisa de uma convenção de nome de agente parametrizada de forma diferente (Codex custom agents são arquivos `.toml` com nome fixo no filename, então a indireção teria que ser um nível a mais: o `.conf` aponta para QUAL arquivo `.toml` chamar). |

**Conclusão da comparação:** a distância entre o script local e o script público é pequena e mecânica —
não é reescrita, é **extração de constantes para uma função `load_config()` + `config_csv()` idêntica nos
3 scripts** (mesmo padrão copiado literalmente em `wiki-lint.py`, `docs-wiki-lint.py` e `ref-integrity.py`
— nenhuma abstração compartilhada entre eles, cada script tem sua própria cópia da função de 15 linhas,
o que é uma duplicação DRY-violável que o próprio kit não resolveu). Para o `docs-wiki-lint.py` há
adicionalmente as 4 checagens novas e o modo diff-aware, que são funcionalidade nova, não só parametrização.

---

## (c) CI e pre-commit — o que rodam de fato

### `.github/workflows/wiki-integrity.yml` (raiz, 33 linhas)

Dispara em `push` para `main` e em `pull_request` (sem filtro de `paths:` — roda em QUALQUER push/PR,
diferente do CI parametrizado dentro de `artefatos/`, que tem filtro de `paths:`). Dois passos:

1. `python3 scripts/wiki-lint.py` (lint global, sempre).
2. Lint diff-aware: calcula `BASE` (`pull_request.base.sha` ou `event.before`), e se não for o SHA zero
   (primeiro push de uma branch nova), roda `python3 scripts/wiki-lint.py --diff-base "$BASE"`; senão cai
   de volta no lint global.

Faz `checkout@v4` com `fetch-depth: 0` (histórico completo — necessário porque o diff-aware precisa
comparar contra um commit-base arbitrário, não só o HEAD~1).

### `.pre-commit-config.yaml` (raiz, 14 linhas)

2 hooks locais (`repo: local`, roda o interpretador Python do sistema, não um ambiente isolado
`pre-commit` tradicional): `guto-wiki-lint-staged` (`--staged`) e `guto-wiki-lint-global` (sem args),
ambos com `pass_filenames: false` (o script decide o que varrer, não recebe lista de arquivos do
pre-commit framework).

### `artefatos/github-workflows/docs-integrity.yaml` (parametrizado, 66 linhas) — 3 diferenças vs a raiz

Comparado ao `wiki-integrity.yml` da raiz E ao `docs-integrity.yaml` LOCAL do learnhouse (já existente em
`/home/augusto/code/learnhouse/.github/workflows/docs-integrity.yaml`), a versão em `artefatos/` tem:

1. **Filtro de `paths:`** (`docs/**`, `**/*.md`, `scripts/docs-wiki-lint.py`, `scripts/ref-integrity.py`,
   `.ref-integrity-allowlist`) — o CI local e o público têm o MESMO filtro; a raiz do guto-wiki (para o
   wiki público em si) não filtra porque o repo inteiro é doc.
2. **Passo extra "Ref-integrity — self-test do detector"** (`ref-integrity.py --selftest`) — presente em
   AMBOS o `artefatos/` e o local (`docs-integrity.yaml` local Linha 39-40) — portanto **já implementado
   localmente**, não é gap.
3. **Diferença real**: o local tem `workflow_dispatch:` extra no trigger (Linha 8) que o `artefatos/` não
   tem — trigger manual via GitHub UI, presente só no local.

**Achado de reconciliação**: comparando meu `diff` mental linha a linha, `docs-integrity.yaml` local e
`artefatos/github-workflows/docs-integrity.yaml` público são **funcionalmente idênticos** (mesmos 2 jobs
de ref-integrity — range no push, range no PR —, mesmo self-test, mesmo `EVENT_BEFORE` fallback para
`HEAD~1`), exceto o `workflow_dispatch:` a mais no local e o filtro de `paths:` inclui
`'.github/workflows/docs-integrity.yaml'` no local (auto-referência do workflow) que falta no público.
**O CI de docs-integrity já está effectively portado/idêntico entre os dois repos — não há gap aqui.**
O que falta é o CI **equivalente da raiz** (`wiki-integrity.yml`, que roda `wiki-lint.py`, o lint do
"repo público em si") — mas esse script (`scripts/wiki-lint.py`) não tem equivalente conceitual local
porque é o lint de UM wiki público standalone, não de um repo de produto com `docs/` como subdiretório.

---

## (d) `artefatos/` como kit de instalação — quão pronto está

**Nota: 8,5/10 como kit de PARAMETRIZAÇÃO DE PATHS; 3/10 como kit de INSTALAÇÃO AUTOMATIZADA.**

O que EXISTE e está pronto para copiar:

- Roteiro de instalação manual em 9 passos, escrito em prosa
  (`2026-07-07-apanhado-padronizacao-documentacao.md` §6, Linhas 113-127) — cada passo é um `cp` + ajuste
  manual de config. **Não há script de instalação/bootstrap** (`install.sh`, `setup.py`, gerador
  interativo) — é 100% "copie e edite manualmente". Para o framework portátil que estamos planejando
  (análogo a `understand-anything`, que tem um comando de setup automatizado), este é o gap mais evidente:
  o guto-wiki documenta O QUE copiar mas não automatiza o COMO.
- `docs-tooling.conf` já é um template completo e comentado (58 linhas, values de exemplo reais do
  learnhouse) — funciona como "arquivo de config a preencher", análogo a um `.env.example`.
- 4 skills (`.md`) prontas para colar em `.claude/skills/` ou `.agents/skills/` — mas ainda citam nomes de
  skill fixos internamente em alguns pontos: `$clarification-plan` (hardcoded, não parametrizado por
  `CLARIFICATION_PLAN_SKILL` na skill `adversarial-review/SKILL.md` Linha 166 e 168) — inconsistência: a
  MESMA skill usa `ADVERSARIAL_REVIEWER_AGENT` (indireção) para o revisor mas `$clarification-plan`
  (hardcoded) para o companion — parametrização incompleta dentro do próprio kit.
- 2 hooks shell (`githooks/pre-commit`, `hooks/lessons-inject.sh`) — funcionam standalone, sem dependência
  de instalar nada além de copiar + `git config core.hooksPath .githooks` (mencionado no passo 6 do
  roteiro, não automatizado).
- Não há **CLAUDE.md completo** pronto para uso — é um CLAUDE.md CURADO (187 linhas, só metodologia),
  explicitamente descrito como "extraído e sanitizado", não como "cole isto no seu projeto e funciona".
  Falta a parte de "como injetar isso automaticamente num CLAUDE.md existente sem sobrescrever" — hoje é
  copy-paste manual de blocos.
- Não há dependência declarada (`requirements.txt`/`pyproject.toml`) — os scripts são Python stdlib puro
  (`argparse`, `re`, `subprocess`, `pathlib`, `json`, `urllib.parse`) — **isso é uma vantagem real para
  portabilidade**: zero instalação de pacote, só `python3 >= 3.12` (usa `X | Y` type hints style moderno,
  `from __future__ import annotations`).
- **Não há teste automatizado do próprio kit** além do `--selftest` embutido no `ref-integrity.py` (que
  testa a lógica do detector, não testa "o kit instala corretamente em um repo vazio").
- **Não há versionamento do kit** (não há `VERSION`, não há tag de release, não há CHANGELOG) — cada
  atualização é um novo commit no `log.md`; não há forma de um repo destino saber "estou na versão X do
  kit, existe atualização".

---

## (e) DIFF vs local — o que existe no `guto-wiki` e NÃO existe em `harness-wiki` nem no harness vivo

Cruzamento real (não por memória): busquei cada artefato do guto-wiki contra
`/home/augusto/code/learnhouse/.claude`, `/home/augusto/code/learnhouse/scripts`,
`/home/augusto/code/learnhouse/docs`, `/home/augusto/code/learnhouse/tasks`,
`/home/augusto/code/learnhouse/.githooks`, `/home/augusto/code/learnhouse/.github/workflows` e
`/home/augusto/code/harness-wiki`.

### Existe no público, AUSENTE localmente (gap real de funcionalidade)

1. **Arquivo `.conf` central** (`docs-tooling.conf`/`wiki-tooling.conf`) — **0 arquivos `.conf` no
   learnhouse** (`find` confirmado, 0 resultados). Todo path vive hardcoded em `.claude/CLAUDE.md`,
   `.claude/loop.md`, dentro dos próprios scripts Python, e em cada `SKILL.md`. Este é o gap estrutural
   nº 1 para o framework portátil — sem ele, nenhum outro artefato pode ser "copiado e apontado" para um
   repo novo sem edição manual de N arquivos diferentes.
2. **Modo diff-aware do lint** (`--worktree`/`--staged`/`--diff-base`) no `docs-wiki-lint.py` — o local
   (`scripts/docs-wiki-lint.py`, 166 linhas) só aceita `--scope`/`--strict-naming`. O comportamento
   "markdown novo/movido/removido exige log.md no mesmo diff" (política mecânica que fecha o loop de
   auto-melhoria) **não existe hoje no CI nem no pre-commit local** — o `.pre-commit-config.yaml` também
   não existe localmente (confirmado: `find -iname '.pre-commit-config.yaml'` = 0 resultados). O único
   guard de commit local é o `.githooks/pre-commit` rodando `ref-integrity.py --staged`, que NÃO checa a
   política "novo doc precisa de log.md".
3. **`check_log_format`** (log fora de ordem temporal decrescente) e **`check_frontmatter_updated`**
   (`updated:` fora de `YYYY-MM-DD`) — nenhuma das duas checagens roda hoje no lint local. `docs/log.md`
   e categorias locais poderiam ter entradas fora de ordem sem serem pegas.
4. **`check_stray_tool_tags`** (regex `STRAY_TOOL_RE` que pega tags de invocação de ferramenta LLM coladas
   por engano em markdown, ex. fechamento de `<content>`/`<invoke>`/`<invoke>`/`<parameter>`) —
   ausente localmente. É uma proteção específica contra um bug real de copy-paste de transcript de agente
   para dentro de um `.md` (cenário plausível dado o volume de sessões de agente que geram os docs deste
   repo).
5. **`--selftest` do próprio `docs-wiki-lint.py`** rodando em CI — o local já tem `ref-integrity.py
   --selftest` no CI (`docs-integrity.yaml` Linha 39-40), mas não há selftest equivalente para o
   `docs-wiki-lint.py` (nem no público, à parte — o selftest é só do `ref-integrity.py` nos dois lados).
6. **Pacote de nomes de subagent parametrizados por config** (`ADVERSARIAL_REVIEWER_AGENT` etc.) — local
   usa nomes fixos (`learnhouse-adversarial-reviewer`, arquivo `.codex/agents/learnhouse-adversarial-
   reviewer.toml`). Trocar de projeto hoje exigiria renomear arquivos `.toml` e todas as referências nas
   SKILL.md — o público resolve isso com 1 nível de indireção.
7. **Skill `scope-wiki-lint` genérica lendo `LEGACY_WIKI_SCOPE`** — local tem
   `design-system-wiki-lint.py` com `"design-system"` hardcoded (Linha 18) em vez de ler de config.

### Existe local, AUSENTE (ou mais fraco) no público — coisas que o framework portátil NÃO deve perder ao portar

1. **`understand-apps-diff-guard.sh`** (hook local) e **`understand-context-inject.py`** — o público só
   documenta a REGRA (`UNDERSTAND_CHANGED_FILES_CMD` no `.conf`), não publica os hooks que ENFORÇAM a
   regra (o guard que bloqueia usar `git diff` sem `--relative=apps`). Isso é esperado — são específicos
   do monorepo `apps/`, mas confirma que o kit público é "documentação + lint de docs", não "todo o
   harness operacional" (hooks de PreToolUse, Stop gates, etc. ficam em `agent-swarm`, não em
   `guto-wiki` — conforme o próprio capítulo 14 do `harness-wiki` já mapeou).
2. **Marathon** (`.claude/runs/`, `marathon-stop-gate.sh`, `marathon-reinject.sh`,
   `marathon-precompact.sh`) — sem equivalente em nenhum dos 27 arquivos do guto-wiki. É harness de
   execução longa, fora do escopo "wiki de documentação" deste repo específico (mas dentro do escopo do
   `agent-swarm`, que é a outra investigação).
3. **`clarification-plan` como skill separada com parametrização própria** — o guto-wiki referencia
   `$clarification-plan` (hardcoded, Linha 166/168 de `adversarial-review/SKILL.md`) mas não inclui o
   arquivo da skill em si nos 27 arquivos — é citada, não publicada.

---

## Observações estruturais para o plano do framework portátil

1. **O maior valor do `guto-wiki` para o plano não é código novo — é o PADRÃO de parametrização já
   validado**: uma função `load_config()` de ~15 linhas, sem dependência externa, com fallback de 3 nomes
   de arquivo (`docs-tooling.conf` → `.docs-tooling.conf` → `wiki-tooling.conf`), replicada
   independentemente (copy-paste, não import) em 3 scripts. Para o framework portátil, a decisão de design
   correta é **extrair essa função para 1 módulo compartilhado** (`scripts/_tooling_conf.py` ou
   equivalente) em vez de repetir a cópia — o próprio kit público NÃO fez essa dedução (confirmado: os 3
   `load_config()` em `docs-wiki-lint.py`, `ref-integrity.py`, `scope-wiki-lint.py` são idênticos
   byte-a-byte mas implementados 3 vezes).
2. **A convenção `.conf` (não YAML/TOML/JSON) é uma escolha deliberada e correta para este caso**: zero
   dependência de parser externo (`configparser` do stdlib teria seções `[x]` que o formato não usa;
   `tomllib` só é stdlib a partir do Python 3.11 e ainda exigiria import condicional; `KEY=value` +
   `split("#",1)` é ~10 linhas e roda em qualquer Python). Recomendo manter o mesmo formato no framework
   portátil, não trocar por YAML — o ganho de expressividade não paga o custo de dependência.
3. **O roteiro §6 do `2026-07-07-apanhado...md`** (9 passos) é, na prática, o primeiro rascunho do plano
   de "instalador" que este projeto quer construir — mas é manual. O ganho concreto e mensurável de
   automatizar (script `bootstrap-wiki.sh` ou comando `/wiki-init`) sobre o roteiro manual atual: elimina
   os passos 1 (copiar+ajustar 20 chaves), 3 (criar 2 arquivos vazios com formato específico), 6 (ativar
   git hook via `git config`) como fontes de erro humano — mas ainda faltaria decidir, no plano, se o
   instalador é um script Python standalone (portável, sem dependência do Claude Code) ou uma skill/slash
   command (só funciona dentro do harness Claude Code/Codex já rodando).
4. **Gap de nomenclatura Codex**: a parametrização de nome de subagent (`ADVERSARIAL_REVIEWER_AGENT` etc.)
   funciona bem para Claude Code (`Agent tool` referencia por string livre), mas para Codex custom agents
   o nome do arquivo `.toml` em `.codex/agents/` PRECISA bater com o nome esperado — a indireção via
   `.conf` resolve a REFERÊNCIA na skill, mas não resolve sozinha o problema de instalar o arquivo
   `.toml` renomeado no repo destino. O plano do framework portátil precisa tratar isso como um passo de
   template (substituição de placeholder no nome do arquivo, não só no conteúdo).
