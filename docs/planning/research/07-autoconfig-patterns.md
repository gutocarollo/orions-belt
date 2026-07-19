# Investigação 7 — Padrão de auto-configuração de understand-anything e hookify

> Fonte: leitura direta do disco em `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/` (plugin v2.8.1, marketplace `understand-anything`) e `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/` (marketplace `claude-plugins-official`). Todos os paths e números de linha citados abaixo foram lidos nesta sessão (2026-07-17), não de memória. Cruzado com o estado real do learnhouse em `/home/augusto/code/learnhouse/apps/.understand-anything/` e com os capítulos já existentes em `/home/augusto/code/harness-wiki/chapters/{07-hookify,13-understand-anything}.md`.

---

## 0. Tese central

Os dois plugins resolvem o MESMO problema de design — "como um motor genérico, versionado uma vez no plugin, se comporta de forma diferente em cada projeto sem o projeto precisar tocar no código do motor" — com duas topologias de config distintas porque os domínios são diferentes:

| | understand-anything | hookify |
|---|---|---|
| Problema | 1 pipeline determinístico + LLM que precisa adaptar-se à *estrutura* de qualquer repo (linguagens, categorias, ignore, incremental) | N guardas independentes que o projeto quer *declarar* ad-hoc (comandos proibidos, padrões de código) |
| Topologia de config | **1 arquivo JSON central por campo** (`config.json`, `meta.json`, `.understandignore`) — schema fixo, poucos campos | **N arquivos markdown soltos**, glob por convenção de nome (`hookify.*.local.md`) — schema por regra, quantidade variável |
| Onde mora o config | `<PROJECT_ROOT>/.understand-anything/` (dentro do projeto, mas em diretório próprio) | `<CWD>/.claude/` (dentro do diretório de config do próprio Claude Code) |
| Quem lê o config | Scripts `.mjs`/`.py` do plugin, chamados por um agente orquestrador (SKILL.md, 7 fases) | Hooks Python do plugin, chamados automaticamente pelo runtime a cada evento (sem agente no meio) |
| Fallback se config ausente/malformado | Gera config default (`.understandignore` starter) ou trata como "primeira execução" (full analysis) | Lista de regras vazia — plugin vira no-op silencioso |

Essa dualidade é o argumento central para o framework portátil: **pipelines de análise pesada** (grafo de código, onboarding, diff review) devem seguir o padrão understand-anything (1 config central + scripts determinísticos + fases orquestradas por skill); **guardas comportamentais** (o que já é 90% do harness do learnhouse — `.claude/hookify.*.local.md`, Stop hooks, PreToolUse gates) devem seguir o padrão hookify (motor único no plugin/framework, N arquivos de regra soltos no projeto).

---

## Parte A — understand-anything: blueprint determinístico vs LLM

### A.1 Anatomia do plugin no disco

```
understand-anything/2.8.1/
├── .claude-plugin/plugin.json      # nome/versão/homepage (Egonex-AI/Understand-Anything no GitHub)
├── package.json                    # @understand-anything/skill — depende de @understand-anything/core (workspace)
├── hooks/
│   ├── hooks.json                  # PostToolUse(Bash) + SessionStart — dispara auto-update
│   └── auto-update-prompt.md       # o "programa" que o hook manda o agente executar
├── agents/                         # 9 subagents LLM (project-scanner, file-analyzer, architecture-analyzer, tour-builder, assemble-reviewer, graph-reviewer, domain-analyzer, article-analyzer, knowledge-graph-guide)
├── skills/understand/
│   ├── SKILL.md                    # orquestrador de 7 fases (839 linhas) — é o "cérebro" do /understand
│   ├── scan-project.mjs            # scanner 100% determinístico (802 linhas)
│   ├── extract-import-map.mjs      # resolução de imports via tree-sitter (1667 linhas, 12 linguagens)
│   ├── compute-batches.mjs         # batching semântico via Louvain (588 linhas)
│   ├── build-fingerprints.mjs      # baseline de fingerprints estruturais (90 linhas)
│   ├── generate-ignore.mjs         # gera .understandignore inicial (66 linhas)
│   ├── extract-structure.mjs       # (334 linhas, usado por build-fingerprints)
│   ├── languages/*.md, frameworks/*.md, locales/*.md  # contexto injetável por linguagem/framework/idioma detectado
│   └── skills/understand-{chat,dashboard,diff,domain,explain,knowledge,onboard}/  # 7 skills satélite
└── packages/core/                  # a lib TS compartilhada (dist/index.js é o que os .mjs importam)
    └── src/{ignore-filter,ignore-generator,fingerprint,change-classifier,staleness,schema,index}.ts
```

**Achado-chave 1** — o "motor" real não é o SKILL.md (que é prosa para o agente seguir), é `packages/core/dist/index.js` + os `.mjs` standalone em `skills/understand/`. O SKILL.md é o *orquestrador* que decide QUANDO chamar cada script determinístico e QUANDO dispachar um subagente LLM. [`skills/understand/SKILL.md:14-16`](../../../../../../home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/SKILL.md) declara isso explicitamente na tabela de flags.

### A.2 Resolução de PROJECT_ROOT e PLUGIN_ROOT (a parte que importa para portabilidade multi-agente)

`SKILL.md` Fase 0 tem duas resoluções de path separadas e não-triviais:

1. **PROJECT_ROOT** (linhas 46-72): parseia `$ARGUMENTS` por um path; se ausente usa CWD; **detecta git worktree** comparando `git rev-parse --git-dir` vs `--git-common-dir` e redireciona para o repo principal (`.understand-anything/` num worktree Claude Code é efêmero — issue #133 citada no próprio arquivo).
2. **PLUGIN_ROOT** (linhas 73-119): cascata de candidatos, NUNCA assume que o path relativo do skill resolve, porque symlinks de instalação variam por agente:
   ```
   $CLAUDE_PLUGIN_ROOT                                    # Claude Code runtime var
   $HOME/.understand-anything-plugin
   <resolvido de ~/.agents/skills/understand via realpath>
   <resolvido de ~/.copilot/skills/understand via realpath>
   $HOME/.codex/understand-anything/understand-anything-plugin
   $HOME/.opencode/understand-anything/understand-anything-plugin
   $HOME/.pi/understand-anything/understand-anything-plugin
   $HOME/understand-anything/understand-anything-plugin
   ```
   Validação de cada candidato: `[ -f "$candidate/package.json" ] && [ -f "$candidate/pnpm-workspace.yaml" ]` (linha 95). Se `packages/core/dist/index.js` não existir, builda on-the-fly com `pnpm install && pnpm --filter @understand-anything/core build` (linhas 116-118).

**Achado-chave 2** — esta é literalmente a arquitetura que o pedido do dono quer replicar: **um motor que funciona em Claude Code, Codex, opencode, Copilot CLI e "pi"** sem reescrever nada, resolvendo o próprio root por uma lista ordenada de convenções por agente. É o precedente direto para "integrar Claude Code E Codex" no framework portátil — cada candidato na lista é literalmente `$HOME/.<agent-name>/<plugin>/`.

### A.3 O config central do projeto (3 arquivos, schema mínimo)

Confirmado contra o estado real do learnhouse em `/home/augusto/code/learnhouse/apps/.understand-anything/`:

- **`meta.json`** — a "etiqueta de validade". Schema (visto ao vivo):
  ```json
  { "lastAnalyzedAt": "ISO8601", "gitCommitHash": "...", "version": "1.0.0", "analyzedFiles": 1748 }
  ```
  É o ANCHOR do princípio incremental inteiro: tudo decide "full vs incremental vs skip" comparando `gitCommitHash` armazenado contra `git rev-parse HEAD` atual ([`SKILL.md:167,182`](.)).
- **`config.json`** — preferências do usuário, schema aberto/extensível: `{"outputLanguage": "pt-BR"}` no learnhouse hoje; também aceita `{"autoUpdate": true|false}` ([`SKILL.md:136-139`](.)). É o único arquivo que representa "config central parametrizável" no sentido que o dono do framework portátil está buscando — mas note que é **plano, sem nesting profundo, cada feature = 1 campo top-level**.
- **`.understandignore`** — sintaxe gitignore, 3 camadas de merge determinístico em [`packages/core/src/ignore-filter.ts:81-104`](.): (1) `DEFAULT_IGNORE_PATTERNS` hardcoded no core (37 padrões: `node_modules/`, `.git/`, `dist/`, `*.lock`, binários, `*.min.js`, etc. — linhas 9-70), (2) `.understand-anything/.understandignore`, (3) `.understandignore` na raiz do projeto — última camada pode usar `!negation` para reincluir algo excluído por default. **Não existe herança de config entre projetos** — cada repo tem seu próprio `.understandignore` do zero (mitigado pelo gerador, ver A.4).

**Achado-chave 3** — `fingerprints.json` é um QUARTO arquivo de estado, mas não é "config" — é cache derivado (hash SHA-256 + assinatura estrutural por arquivo), gerado por `build-fingerprints.mjs` e nunca editado por humano. No learnhouse hoje: 4,1 MB, [`apps/.understand-anything/fingerprints.json`](.) — 1748 entradas.

### A.4 Determinístico vs LLM — onde a linha é traçada (blueprint mais reaproveitável)

O plugin documenta essa fronteira explicitamente em COMENTÁRIOS DE CÓDIGO (não só no SKILL.md), o que é sinal de decisão de arquitetura deliberada:

> `scan-project.mjs:1-24` — "Deterministic file enumeration + language/category detection [...] Replaces the LLM-written prose scanner that used to (a) author a per-run Node.js script, (b) walk the file tree, and (c) classify each file via lookup tables in LLM context — a pure rule-lookup pass that was being billed at LLM rates and adding many minutes of per-run latency."

Isso é uma confissão de refactor: a v1 do produto fazia a LLM escrever e rodar um scanner ad-hoc a cada execução (caro, lento, não-determinístico); a v2 move 100% da enumeração para um script versionado. O padrão fica:

| Fase | Determinístico (script no plugin) | LLM (subagent) |
|---|---|---|
| 1 SCAN | `scan-project.mjs` — enumeração (`git ls-files -z -co --exclude-standard`, fallback recursivo), detecção de linguagem/categoria por tabela de extensão+filename, contagem de linhas, `estimateComplexity` | Só a leitura de README/manifest para sintetizar `name`/`description`/`frameworks` narrativos (`project-scanner.md` Step A, [linhas 27-49](.)) |
| 1 (import) | `extract-import-map.mjs` — resolução de import via tree-sitter, 12 linguagens (TS/JS/Python/Go/Rust/Java/Kotlin/C#/Ruby/PHP/C/C++) | nenhuma — linguagens fora da lista recebem `[]`, sem fallback LLM ([`project-scanner.md:160`](.)) |
| 1.5 BATCH | `compute-batches.mjs` — clustering Louvain (`graphology-communities-louvain`) sobre o grafo de imports para produzir lotes semanticamente coesos | nenhuma |
| 2 ANALYZE | `merge-batch-graphs.py` — merge/normalize/dedupe de nós e arestas, linker de `tested_by` | `file-analyzer` subagent produz os `GraphNode`/`GraphEdge` por arquivo (síntese de summary/tags/complexity) |
| 3 REVIEW | `merge-batch-graphs.py` stderr | `assemble-reviewer` subagent |
| 4 ARCHITECTURE | normalização de shape (unwrap/rename/dedup) após o subagent responder | `architecture-analyzer` subagent identifica layers a partir da árvore de diretórios |
| 5 TOUR | idem | `tour-builder` subagent |
| 6 REVIEW | script inline `ua-inline-validate.cjs` (validação de schema, gerado on-the-fly, [`SKILL.md:599-663`](.)) OU `graph-reviewer` subagent se `--review` | — |
| 7 SAVE | `build-fingerprints.mjs` (baseline tree-sitter para incremental futuro) | nenhuma |

**Regra de ouro extraída**: enumeração de arquivos, classificação por extensão/nome, contagem, resolução de import e diffing estrutural são SEMPRE determinísticos. Síntese de narrativa (nome, descrição, camadas arquiteturais, tour pedagógico, summary por arquivo) é SEMPRE LLM. A linha nunca é ambígua no código real.

### A.5 O ciclo de auto-update incremental (zero-token gate)

Este é o mecanismo mais sofisticado e o que mais vale portar 1:1 para o framework:

1. **Gatilho** — [`hooks/hooks.json`](.) registra 2 hooks:
   - `PostToolUse` matcher `Bash`: regex `git\s+(commit|merge|cherry-pick|rebase)` no comando + `.understand-anything/config.json` tem `"autoUpdate":true` + grafo existe → imprime instrução para o agente ler `auto-update-prompt.md` (linha 9).
   - `SessionStart`: mesma condição de `autoUpdate:true`, MAS também compara `meta.json.gitCommitHash` contra `git rev-parse HEAD` — só dispara se DIVERGIREM (linha 19). Isso cobre o caso "commit feito fora da sessão do Claude" (outro agente, terminal manual).
   - Ambos são **puro shell one-liner com `&&` encadeado** — nenhuma dependência de runtime além de `grep`/`node -p`/`git`. Fail-open: se qualquer condição falhar, o `|| true` final garante exit 0.

2. **`auto-update-prompt.md`** (não é skill nem comando — é "hook-triggered internal prompt", linha 1-3) roda 4 fases:
   - Fase 0: pré-flight (existe grafo? existe meta? hash mudou? filtra para extensões de código-fonte; aplica `.understandignore`) — **zero custo de LLM**.
   - Fase 1: `fingerprint-check.mjs` (script gerado inline pelo agente, mas 100% determinístico) — compara SHA-256 de conteúdo primeiro (fast path `NONE`); se diferente, extrai funções/classes/imports/exports via tree-sitter e compara *assinaturas* (não corpo) → classifica `NONE|COSMETIC|STRUCTURAL` — **ainda zero custo de LLM**.
   - Decisão ([`change-classifier.ts:21-87`](.)): `structuralCount === 0` → `SKIP`; `>30 arquivos OU >50% do grafo` → `FULL_UPDATE` (recomenda `--full`, não executa sozinho); `novo/removido diretório-top-level OU >10 arquivos` → `ARCHITECTURE_UPDATE`; caso contrário → `PARTIAL_UPDATE`.
   - Fase 2: **só aqui entra LLM**, e só para os arquivos `filesToReanalyze` (não o repo inteiro).
   - Fase 3: merge + save + **fingerprints.json atualizado via LOAD-PATCH-SAVE nunca OVERWRITE** ([`auto-update-prompt.md:243-290`](.)) — comentário no próprio arquivo cita um bug real (issue #152): sobrescrever só as entradas do batch apaga o fingerprint de todo o resto do repo, fazendo TODO update futuro escalar para `FULL_UPDATE` permanentemente. A correção é: sempre carregar o dict inteiro, patchear só as chaves tocadas, salvar o dict inteiro de volta — com um guard explícito (`existedAndNonEmpty && before === 0` → aborta) contra falha silenciosa de leitura.

**Achado-chave 4** — o "zero-token gate" (fingerprint SHA-256 + assinatura estrutural via tree-sitter, tudo antes de qualquer LLM ser invocada) é o padrão que resolve exatamente o mesmo problema de custo que o `understand-apps-incremental` do learnhouse resolve por outra via (guard de path). São dois problemas diferentes: understand-anything otimiza "não gastar LLM à toa"; o guard do learnhouse (capítulo 13 do harness-wiki) resolve "não deixar o diff silenciosamente vazio por causa de `PROJECT_ROOT=apps` vs git root real". **Os dois são compatíveis e compostos** — o framework portátil precisa dos dois: fingerprint gate (custo) + path-relative guard (correção), documentados como camadas independentes.

### A.6 Tabelas determinísticas (para copiar/adaptar, não reinventar)

`scan-project.mjs` linhas 105-193 (`LANGUAGE_BY_EXT`, ~50 extensões), 204-212 (`LANGUAGE_BY_FILENAME`: `Dockerfile`/`Makefile`/`Jenkinsfile`/`Procfile`/`Vagrantfile`), 285-338 (`CATEGORY_BY_EXT`), 345-355 (`INFRA_FILENAMES`). Regra de prioridade documentada linha 358-417 (`detectCategory`): LICENSE é exceção (`code`, não `docs`); infra por filename vence infra por extensão vence config por extensão; fallback final é sempre `code`. `estimateComplexity` (linhas 435-440): `small` ≤30 arquivos, `moderate` ≤150, `large` ≤500, `very-large` >500 — thresholds fixos, sem config exposta ao usuário (achado de gap: não é parametrizável hoje).

`ignore-filter.ts:9-70` — os 37 `DEFAULT_IGNORE_PATTERNS` hardcoded (não overridable exceto por negação explícita `!padrão` no `.understandignore` do projeto).

---

## Parte B — hookify: motor único + config declarativa em N arquivos

(Capítulo 07 do harness-wiki já documenta bem o pipeline PreToolUse específico do learnhouse — este relatório foca no que falta: a mecânica GENÉRICA do plugin, útil como blueprint, não como caso de uso.)

### B.1 Registro de hooks — nenhum matcher, tudo delega pro engine

[`hooks/hooks.json`](.) registra **4 hook points** (`PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`), cada um com UM ÚNICO comando: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<evento>.py"`, timeout 10s, **sem `matcher`** (roda em TODA invocação de ferramenta, todo Stop, todo prompt). A filtragem por tipo de evento/ferramenta acontece DENTRO do script Python, não na declaração do hook. Isso é o oposto do padrão nativo do Claude Code (que filtra por `matcher` na declaração) — hookify escolheu empurrar a decisão para dentro do motor porque o motor já precisa ler `tool_name` do JSON de qualquer forma para extrair o campo certo.

Os 4 scripts (`pretooluse.py`, `posttooluse.py`, `stop.py`, `userpromptsubmit.py`) são **quase idênticos byte-a-byte** — confirmado comparando `pretooluse.py` e `stop.py` linha a linha: mesmo boilerplate de import com fallback (`sys.path.insert` de `CLAUDE_PLUGIN_ROOT`, linhas 13-24), mesmo `try/except Exception` envolvendo tudo, mesmo `finally: sys.exit(0)`. A única diferença é qual `event` string é passado para `load_rules(event=...)` e como o `tool_name` é mapeado (`pretooluse.py:38-41`: `Bash→bash`, `Edit|Write|MultiEdit→file`; `stop.py:38`: hardcoded `event='stop'`).

**Achado-chave 5** — "sempre `exit(0)`, nunca deixar o hook quebrar a sessão" é uma decisão de design repetida em CADA um dos 4 scripts, não centralizada — é duplicação de boilerplate que o framework portátil deveria refatorar para 1 wrapper genérico (`run_hook(event_name, entry_fn)`) em vez de copiar o padrão 4x.

### B.2 Config = glob de markdown no projeto, não no plugin

[`core/config_loader.py:210`](.): `pattern = os.path.join('.claude', 'hookify.*.local.md'); files = glob.glob(pattern)`. **Path relativo ao CWD** — funciona porque o Claude Code sempre invoca hooks com CWD = raiz do projeto. Isso é uma fragilidade implícita (não documentada como tal no código): se o motor rodasse de outro CWD, o glob simplesmente não encontraria nada e devolveria lista vazia — fail-open por acidente de design, não por guard explícito.

Cada arquivo é YAML frontmatter (parser CUSTOM escrito à mão em `extract_frontmatter()`, [`config_loader.py:87-195`](.) — não usa PyYAML, suporta listas indentadas e dicts inline/multi-linha via parsing manual de indentação) + corpo markdown = mensagem exibida ao usuário/agente quando a regra dispara. Schema do `Rule` dataclass ([linhas 32-84](.)): `name`, `enabled`, `event` (`bash|file|stop|prompt|all`), `pattern` (legado, 1 regex simples) OU `conditions` (lista de `{field, operator, pattern}`), `action` (`warn|block`), `tool_matcher` (override opcional do matching por tool).

**Fallback de erro por arquivo é granular e não-fatal**: `load_rules()` ([linhas 198-241](.)) tem 3 blocos `except` separados por classe de erro (I/O, parsing, genérico) — cada falha em UM arquivo de regra apenas pula esse arquivo (`continue`) e loga em stderr; nunca aborta o carregamento das outras regras.

### B.3 O engine de avaliação — campo por tool, operador por condição

[`core/rule_engine.py`](.) é ~314 linhas, sem dependência externa além de `re` (regex compilado com `@lru_cache(maxsize=128)`, case-insensitive fixo, [linha 14-24](.)). Fluxo `evaluate_rules()` ([linhas 35-94](.)):
1. Para cada regra: `_rule_matches()` — checa `tool_matcher` (se declarado) e depois EXIGE que **todas** as `conditions` casem (AND lógico, [linha 121-124](.); zero conditions = regra nunca casa, [linha 117](.), previne regra "vazia" acidentalmente sempre-true).
2. Regras que casaram são separadas em `blocking_rules` (`action:block`) vs `warning_rules`. **Block sempre vence** — se qualquer regra bloqueante casou, warnings são ignorados na resposta (mas ainda avaliados).
3. Formato de saída muda por `hook_event_name`: `Stop` → `{"decision":"block","reason":...}`; `PreToolUse|PostToolUse` → `{"hookSpecificOutput":{"hookEventName":...,"permissionDecision":"deny"}}`; outros eventos → só `systemMessage`. **Isso é o contrato exato do protocolo de hooks do Claude Code** — o motor precisa conhecer esse contrato por evento, é acoplamento legítimo (não portável 1:1 para Codex sem tradução).
4. `_extract_field()` ([linhas 182-254](.)) é a peça mais específica-por-ferramenta: mapeia `field` string (`command`, `new_text`/`new_string`, `old_text`/`old_string`, `file_path`, `content`, `reason`, `transcript` [lê arquivo do disco via `transcript_path`], `user_prompt`) para o campo real do JSON de cada tool (`Bash.command`, `Write/Edit.new_string`/`content`, `MultiEdit.edits[].new_string` concatenado). Cada tool nova exigiria adicionar um `elif tool_name == 'X'` aqui — **não é genérico por schema, é hardcoded por tool conhecida**. Isso é um limite real de portabilidade: se o framework quiser suportar tools do Codex com schema diferente, este mapeamento tem que ser duplicado/adaptado, não reaproveitado.

### B.4 A camada "autoconfiguração conversacional" (o análogo LLM do project-scanner Step A)

[`commands/hookify.md`](.) é o comando `/hookify:hookify` — o único ponto do plugin onde uma LLM GERA config (os outros 4 scripts só CONSOMEM config). Fluxo:
1. Se `$ARGUMENTS` vazio, despacha um subagent genérico (`general-purpose`, [linhas 30-58](.)) com prompt fixo: ler as últimas 20-30 mensagens do usuário, procurar 4 padrões (pedido explícito de "não faça X", correção/reversão, reação de frustração, problema repetido), extrair `{category, tool, pattern, context, severity}` por achado.
2. `AskUserQuestion` interativo (3 perguntas: quais comportamentos virar regra [multiSelect], block vs warn por comportamento, refinar o padrão) — **decisão humana no loop**, não autoconfiguração 100% autônoma.
3. Escreve `.claude/hookify.{kebab-case-name}.local.md` no **CWD do projeto**, nunca no plugin (`commands/hookify.md:128`: "Rule files must be created in the current working directory's `.claude/` folder, NOT the plugin directory" — aviso em CAPS no próprio arquivo, sinal de que já foi bug real).
4. Regras ficam ativas imediatamente, sem restart — porque o `config_loader.py` faz glob a cada invocação do hook (nenhum cache de config em memória entre chamadas).

**Achado-chave 6** — o padrão "LLM só participa da GERAÇÃO do config, nunca da AVALIAÇÃO em runtime" é idêntico ao project-scanner do understand-anything (Step A LLM só sintetiza `name`/`description`/`frameworks`; toda avaliação subsequente — scan, ignore, fingerprint, batch — é código puro). É o segundo pilar do padrão "motor no plugin, config no projeto": **motor de RUNTIME é sempre determinístico; LLM só aparece na fase de AUTORIA do config, sob confirmação humana explícita quando a config afeta comportamento bloqueante**.

---

## Síntese — o blueprint replicável para o framework portátil

1. **Separação física engine/config é sempre por diretório, nunca por convenção de nome de campo.** understand-anything: engine em `~/.claude/plugins/.../understand-anything/`, config em `<repo>/.understand-anything/`. hookify: engine em `~/.claude/plugins/.../hookify/`, config em `<repo>/.claude/hookify.*.local.md`. O framework portátil (unificando harness-wiki + guto-wiki + agent-swarm) deveria fixar 1 diretório de config central por projeto (ex.: `<repo>/.agent-harness/` ou reaproveitar `.claude/` já que é convenção compartilhada Claude Code) com sub-arquivos por concern, não um monólito.

2. **Resolução de root do motor em cascata multi-agente é a peça que falta hoje no ecossistema learnhouse/harness-wiki.** O padrão de 8 candidatos do `SKILL.md:85-94` (`$CLAUDE_PLUGIN_ROOT` → `$HOME/.understand-anything-plugin` → symlink resolution → `$HOME/.codex/...` → `$HOME/.opencode/...` → `$HOME/.pi/...` → fallback genérico) é DIRETAMENTE portável: o framework unificado precisa da mesma cascata, trocando os nomes de diretório por convenções Claude Code vs Codex (`AGENTS.md`+`.agents/skills`+`.codex/agents`, já usado no learnhouse conforme `.claude/CLAUDE.md` seção "LearnHouse Codex-native Council").

3. **Fail-open + fail-safe-default é não-negociável em TODA borda de config.** understand-anything: `.understandignore` ausente → gera starter e PARA para confirmação humana (não assume); config.json malformado → nunca visto quebrar (campos são lidos individualmente com grep, não parse estrito). hookify: regra malformada → pulada com log, resto continua; qualquer exceção no hook → sempre `exit(0)`, nunca bloqueia a sessão por bug do próprio guard. O framework portátil deve tratar QUALQUER falha de leitura do config central como "modo default", nunca como crash.

4. **Zero-token gate antes de LLM é padrão obrigatório para qualquer pipeline caro.** O fingerprint SHA-256 + assinatura estrutural (tree-sitter) do understand-anything é o nível de sofisticação certo: hash primeiro (mais barato), assinatura estrutural segundo (ainda determinístico), LLM só no que sobra. Aplica-se a qualquer feature do framework portátil que hoje rode LLM a cada chamada sem checar se algo realmente mudou.

5. **Metadata de staleness = 1 arquivo pequeno com commit hash, sempre.** `meta.json{gitCommitHash}` é o padrão mínimo replicável para qualquer estado derivado do framework que precise saber "estou desatualizado?". É mais simples e mais robusto que o que o learnhouse tem hoje espalhado em CLAUDE.md como hash hardcoded (achado B do capítulo 13 do harness-wiki: o CLAUDE.md cita `5b125ff9...` como "hash atual", mas o `meta.json` real diz `8128e0c8...` — exatamente a classe de bug que ler o arquivo de estado, em vez de decorar o valor, previne).

6. **LLM gera config, motor determinístico avalia config — nunca o inverso.** Replicar isso significa que qualquer feature nova do framework portátil que precise de "regra específica do projeto X" deve seguir o fluxo hookify: subagent lê contexto/conversa → propõe regra → humano confirma (quando a ação é bloqueante) → escreve arquivo declarativo no projeto → motor genérico (já existente, não reescrito) passa a honrar a regra na próxima invocação, sem restart.

---

## Gaps vs. harness-wiki local (docs/harness-wiki atual)

- **Capítulo 13 (`understand-anything.md`, 186 linhas) documenta SÓ o incidente/guard `PROJECT_ROOT=apps` específico do learnhouse** (script `understand-apps-changed-files.sh`, hook `understand-context-inject.py`, guard `understand-apps-diff-guard.sh`, skill `understand-apps-incremental`). **Não documenta nada do mecanismo genérico do PRÓPRIO plugin**: nem a cascata de `PLUGIN_ROOT` multi-agente, nem as 7 fases do SKILL.md, nem `scan-project.mjs`/tabelas determinísticas, nem o ciclo de auto-update via `hooks.json` (`PostToolUse`+`SessionStart`), nem `fingerprint.ts`/`change-classifier.ts` (o "zero-token gate"), nem o `.understandignore` de 3 camadas, nem `config.json`/`meta.json` como padrão de config central. Isso é 100% gap — o capítulo trata o plugin como caixa-preta e documenta apenas a camada de guard construída EM CIMA dele.
- **Capítulo 07 (`hookify.md`, 425 linhas) documenta bem o motor PreToolUse e as 12 regras locais**, mas não cobre: os outros 3 hook points (`PostToolUse`/`Stop`/`UserPromptSubmit` — só menciona de passagem na linha 15), o parser de frontmatter custom (`extract_frontmatter`), nem — o mais relevante para esta investigação — **o fluxo de autoconfiguração via `/hookify:hookify`** (subagent `conversation-analyzer` + `AskUserQuestion` + geração de arquivo `.local.md`). Esse fluxo é exatamente o "análogo LLM" que a Investigação 7 pediu para achar, e não está em lugar nenhum do harness-wiki hoje.
- Nenhum capítulo do harness-wiki hoje descreve o padrão genérico "motor no plugin / config no projeto" como PRINCÍPIO REUTILIZÁVEL — cada capítulo documenta uma instância (hookify no learnhouse, o guard understand-apps) sem extrair a abstração comum. Essa extração é precisamente o conteúdo da seção "Síntese" acima e deveria virar um capítulo novo do framework portátil (ou uma seção do plano), não mais um capítulo de caso-de-uso.

---

## Referências de arquivo (path completo, para o plano)

- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/SKILL.md`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/agents/project-scanner.md`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/scan-project.mjs`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/compute-batches.mjs`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/build-fingerprints.mjs`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/skills/understand/generate-ignore.mjs`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/hooks/hooks.json`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/hooks/auto-update-prompt.md`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/ignore-filter.ts`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/ignore-generator.ts`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/fingerprint.ts`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/change-classifier.ts`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/plugins/discovery.ts`
- `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/packages/core/src/index.ts`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/hooks/hooks.json`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/hooks/pretooluse.py`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/hooks/stop.py`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/core/config_loader.py`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/core/rule_engine.py`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/commands/hookify.md`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/examples/dangerous-rm.local.md`
- `/home/augusto/.claude/plugins/cache/claude-plugins-official/hookify/unknown/examples/require-tests-stop.local.md`
- `/home/augusto/code/learnhouse/apps/.understand-anything/meta.json` (estado real, cross-check)
- `/home/augusto/code/learnhouse/apps/.understand-anything/config.json` (estado real, cross-check)
- `/home/augusto/code/learnhouse/apps/.understand-anything/.understandignore` (estado real, cross-check)
- `/home/augusto/code/harness-wiki/chapters/13-understand-anything.md` (gap analysis)
- `/home/augusto/code/harness-wiki/chapters/07-hookify.md` (gap analysis)
