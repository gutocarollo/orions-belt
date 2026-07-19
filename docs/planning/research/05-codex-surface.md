# INVESTIGAÇÃO 5 — Superfície de configuração do OpenAI Codex CLI

Data: 2026-07-17. Fontes: (a) arquivos locais reais (learnhouse + clone agent-swarm + `~/.codex` global + binário codex-cli **0.144.0-alpha.4** bundled na extensão VS Code `openai.chatgpt-26.707.31428-linux-x64`); (b) docs oficiais `developers.openai.com/codex/*` (308 → `learn.chatgpt.com/docs/*`). Todos os claims sobre o binário foram extraídos por `strings`/`--help`/`features list` do executável real desta máquina.

---

## 0. Veredicto executivo (o que muda no plano)

1. **O Codex HOJE tem hooks nativos, estáveis, com protocolo quase idêntico ao do Claude Code** (`hookSpecificOutput`, `hook_event_name`, `stop_hook_active`, exit code 2 = block). A premissa implícita do dono (agent-swarm compensa ausência de enforcement com witness/ledger em Python) está **desatualizada**: `codex features list` → `hooks  stable  true`. O "limite duro" do framework é bem mais estreito do que o documentado localmente.
2. **Skills do Codex são o MESMO formato SKILL.md do Claude** (frontmatter `name`/`description`), com discovery em `.agents/skills` (walk-up do cwd até o repo root) — exatamente o path que o learnhouse já usa. `~/.codex/skills` local já contém skills sincronizadas de plugins Claude (`understand`, `cloudflare` etc.) funcionando como prova viva de portabilidade.
3. **Custom agents** = `.codex/agents/*.toml` (repo) + `~/.codex/agents/` (user), campos `name/description/developer_instructions/sandbox_mode/model_reasoning_effort` + overrides de config. Fan-out controlado por `[agents] max_threads/max_depth`.
4. **Cadeia AGENTS.md** = global (`~/.codex/AGENTS.override.md` → `~/.codex/AGENTS.md`, primeiro não-vazio) + walk do Git root até o cwd (1 arquivo por diretório: `AGENTS.override.md` → `AGENTS.md` → `project_doc_fallback_filenames`), concatenado root-down, cap `project_doc_max_bytes` (default 32 KiB).
5. Para o framework portátil: **um config central pode gerar TODAS as superfícies Codex** (AGENTS.md, `.codex/config.toml`, `.codex/agents/*.toml`, `.agents/skills/`, `hooks.json`) — a peça que continua sem análogo 1:1 é o par slash-commands/`.claude/commands` (Codex prompts são user-only e **deprecados em favor de skills**) e eventos de hook que o Codex não tem (`SessionEnd`, `Notification`, `PreCompact` existe; ver matriz §5).

---

## 1. FONTE A — superfície local real

### 1.1 `/home/augusto/code/learnhouse/.codex/config.toml` (5 linhas, íntegra)

```toml
project_doc_max_bytes = 65536

[agents]
max_threads = 4
max_depth = 1
```

- Linha 1: dobra o cap default (32 KiB) para não truncar a cadeia `~/.codex/AGENTS.md` + `AGENTS.md` do repo (o AGENTS.md do learnhouse tem ~28 KB sozinho).
- Linhas 3-5: throttle de fan-out. Default oficial atual de `max_threads` é **6** (docs config-reference); o repo pina 4 — espelho do hook `subagent-throttle` do lado Claude (CLAUDE.md §11: "máximo 6 simultâneos").
- O clone agent-swarm tem **byte-a-byte o mesmo arquivo** em `clones/agent-swarm/codex/.codex/config.toml` — é o artefato publicado.
- Config de projeto só é carregada com o projeto **trusted** (em `~/.codex/config.toml`: `[projects."/home/augusto/code/learnhouse"] trust_level = "trusted"`, Linha 9-10).

### 1.2 `/home/augusto/code/learnhouse/.codex/agents/*.toml` (formato real de custom agent)

4 agentes, todos com o mesmo esqueleto (validado por `validate_skills.py` do agent-swarm, campos obrigatórios `name`, `description`, `sandbox_mode`, `developer_instructions`):

| Arquivo | sandbox_mode | reasoning | Papel |
|---|---|---|---|
| `learnhouse-adversarial-reviewer.toml` | `read-only` | `high` | Reviewer com sentinels `ADVERSARIAL-VERIFICATION:` / `PLAN-ADVERSARIAL-VERIFICATION:` (Linhas 24, 34) |
| `learnhouse-context-scout.toml` | `read-only` | `medium` | Context Brief pré-implementação |
| `learnhouse-implementer.toml` | `workspace-write` | `medium` | Só executa plano aprovado |
| `learnhouse-test-auditor.toml` | `read-only` | `medium` | Audita evidência de validação |

Padrões dignos de porte para o framework:
- **Prompt-contrato dentro do TOML** (`developer_instructions = """..."""`), incluindo guardas de domínio (todos os 4 têm o "Understand Anything guard", ex. reviewer Linhas 43-46) — ou seja, o dono replica em PROSA nos 4 agents o que no Claude é hook executável (`understand-apps-diff-guard.sh`). Com hooks Codex nativos isso pode virar guard real.
- **Sandbox como privilégio mínimo por papel** (reviewer/scout/auditor read-only; só implementer escreve).
- Sentinels de saída padronizados = interface parseável entre agente e orquestrador.

### 1.3 `/home/augusto/code/learnhouse/AGENTS.md`

- É **espelho curado do `.claude/CLAUDE.md`** para agentes não-Claude — declarado no comentário das Linhas 1-3: "SEM o bloco de infra/produção (VPS, URLs, portas, credenciais) — deliberado... Ao editar o CLAUDE.md, regenerar este espelho (última sync: 2026-07-06)".
- Diferenças vs CLAUDE.md além da remoção de infra: §6 volta ao formato antigo "até 5 perguntas numeradas" (Linha 236) em vez dos blocos D[n] com trade-offs; não tem §15/§16 (workflow Boris / self-improvement loop) — **drift de sync** entre os dois espelhos (CLAUDE.md evoluiu depois de 2026-07-06).
- Seção "LearnHouse Codex-native Council" (Linhas 75-139) define o fluxo Codex: skills `$learnhouse-delivery-council`/`$clarification-plan`/`$adversarial-review`, custom agents, bloco `ARGS:` textual ("Custom agents Codex não recebem argumentos formais como função; os argumentos são contrato textual obrigatório", Linha 105).
- **Implicação para o framework: manter 2 espelhos na mão é o anti-pattern que o framework deve resolver** — fonte única de config → gerar CLAUDE.md e AGENTS.md com blocos de inclusão/exclusão (ex.: tag "infra-privada" fora do AGENTS.md).

### 1.4 `/home/augusto/code/learnhouse/.agents/skills/` (como o Codex lê)

10 skills, todas `pasta/SKILL.md` com frontmatter YAML `name` + `description` (formato idêntico ao das skills Claude). Uma skill tem subpasta `agents/` com `openai.yaml`:

```yaml
# .agents/skills/learnhouse-delivery-council/agents/openai.yaml
interface:
  display_name: "LearnHouse Delivery Council"
  short_description: "Orquestra entregas LearnHouse"
  default_prompt: "Use $learnhouse-delivery-council com ARGS START_AT=AUTO, ..."
```

- Invocação por `$nome` no prompt (`$learnhouse-delivery-council`) + invocação implícita pela `description`.
- A SKILL.md do council é **dual-runtime por design**: Linha 116 "Claude Code: Agent tool; Codex: custom agent thread"; Linha 153 "Claude Code: SendMessage; Codex: mesma thread"; Linha 233 "Se o mecanismo de subagent estiver indisponivel, PARE e declare o bloqueio". Este é o padrão de escrita cross-runtime que o framework deve adotar em todas as skills orquestradoras.
- A skill `adversarial-review` (Linha 12) codifica a regra "contrato de subagent, nunca inline" também de forma runtime-agnóstica.

### 1.5 `~/.codex/` global (estado real da máquina)

- `~/.codex/AGENTS.md` (17 linhas): persona global compacta (filosofia + Não Reinventar a Roda). Entra ANTES do AGENTS.md do repo na cadeia.
- `~/.codex/config.toml`: `model = "gpt-5.6-luna"`, `model_reasoning_effort = "high"`, `personality = "pragmatic"`, `approval_policy = "never"`, `sandbox_mode = "danger-full-access"`, tabela `[projects."..."] trust_level = "trusted"` por repo, e 6 `[mcp_servers.*]` **HTTP url-based** (ex.: `postgres-learnhouse-prod = http://127.0.0.1:18115/mcp`, Linhas 21-22) — MCP no Codex é config TOML, não `.mcp.json`.
- `~/.codex/rules/default.rules`: mecanismo de **allowlist de comandos** em Starlark-like — `prefix_rule(pattern=["python3", "scripts/design-system-wiki-lint.py"], decision="allow")` — análogo funcional do `permissions.allow` do settings.json do Claude.
- `~/.codex/skills/`: 19 skills presentes, **todas cópias de skills de plugins Claude** (`understand*` = understand-anything, `cloudflare*`, `wrangler`...). O frontmatter delas inclui `argument-hint` além de `name`/`description` — e o binário valida keys permitidas ("Unexpected key(s) in SKILL.md frontmatter" nas strings), então keys extras podem gerar warning; funcionam como prova de que o mesmo SKILL.md serve os dois runtimes.
- `~/.codex/prompts/` não existe nesta máquina; feature deprecada (ver §3.6).

### 1.6 Clone agent-swarm (`clones/agent-swarm/codex/`) — o que o dono já documentou

- `README.md`: pacote "Codex-native do LearnHouse Delivery Council" — ordem fixa `PLAN → PLAN_REVIEW → EXECUTION → EXECUTION_REVIEW`, `START_AT` escolhe o ponto de entrada, sentinels com handoffs obrigatórios `REPLAN-REQUEST/REPLAN-CONSUMED` e `FIX-REQUEST/FIX-CONSUMED` (Linhas 203-248), pares inválidos documentados (Linhas 257-276).
- **Camada de contrato executável** (Linhas 278-333): `scripts/validate_contract.py` (ponto único), `validate_skills.py` (frontmatter + TOML + openai.yaml, sem deps externas), `verify_witness.py` + `verification/witness-fixes.json` (marcadores load-bearing não podem sumir), `agent_swarm_ledger.py` (JSONL em `.agent-swarm/runs/`), `render_prompt.py` (gera bloco `ARGS:` válido), `tests/test_agent_contract.py`. AGENTS.md do pacote (Linhas 18-21): "Nao transforme esses scripts em segundo orquestrador".
- **Leitura crítica**: essa camada inteira é um **substituto de hooks construído quando o Codex não tinha hooks**. Com `hooks` stable, parte dela (witness no Stop, ledger no PostToolUse/SubagentStop, gate de sentinel no Stop) pode virar enforcement de verdade — mantendo os scripts como implementação chamada pelos hooks (não jogar fora; religar).
- `codex/AGENTS.md` do pacote também fixa: sem GitHub Actions (validação local/manual), não copiar `.claude/CLAUDE.md`/credenciais para o repo público.

---

## 2. FONTE B — docs oficiais + binário 0.144.0-alpha.4

### 2.1 Cadeia AGENTS.md (doc `codex/guides/agents-md` → `learn.chatgpt.com/docs/agent-configuration/agents-md`)

1. **Global**: `~/.codex/AGENTS.override.md`, senão `~/.codex/AGENTS.md` — "only the first non-empty file at this level".
2. **Projeto**: do **Git root** (ou cwd se não houver) **descendo até o cwd**; em cada diretório, no máximo 1 arquivo: `AGENTS.override.md` → `AGENTS.md` → nomes em `project_doc_fallback_filenames`. **Sim, subdiretórios contam** (por isso o guia oficial recomenda AGENTS.md por sub-pacote em monorepo).
3. **Merge**: concatenação root-down com linhas em branco; arquivos vazios pulados; discovery **para ao atingir `project_doc_max_bytes`** (default **32 KiB**); recomputado a cada run (sem cache).
4. `project_doc_fallback_filenames` permite mapear `CLAUDE.md` como fallback — rota de migração barata para repos que só têm CLAUDE.md.

### 2.2 config.toml — chaves confirmadas (docs + strings do struct `ConfigToml` "with 97 elements")

Relevantes ao framework: `model`, `model_reasoning_effort`, `approval_policy` (`untrusted|on-request|never`), `sandbox_mode` (`read-only|workspace-write|danger-full-access`), `project_doc_max_bytes`, `project_doc_fallback_filenames`, `projects.<path>.trust_level`, `[agents] max_threads` (default 6) / `max_depth` (default 1; root = depth 0) / `job_max_runtime_seconds` (default 1800 p/ CSV jobs) / `interrupt_message` (default true), `[hooks]`, `skills.config` (array `{path, enabled}` — requer restart), `[features]` (`hooks`, `multi_agent` stable/on-default; `memories` experimental), `[mcp_servers.*]` (url HTTP ou command stdio, `bearer_token_env_var`, `startup_timeout_sec`, `enabled_tools`/`disabled_tools`, oauth), `profiles` (`-p` / `$CODEX_HOME/<name>.config.toml`), `notify`, `shell_environment_policy`, `project_root_markers`, `model_instructions_file`, `personality`, `plugins`/`marketplaces`, `requirements.toml` (enterprise: `allow_managed_hooks_only`, `allowed_sandbox_modes`...). Override pontual: `codex -c key=value` (dotted path, valor TOML).
- **Camadas**: managed/enterprise → user `~/.codex/config.toml` → projeto `.codex/config.toml` (só se trusted; certas chaves proibidas em project-scope: provider, auth, telemetry) → `-c` CLI.
- Strings do binário confirmam localmente: `project_doc_max_bytes`, `project_doc_fallback_filenames`, `max_threads`, `max_depth`, `job_max_runtime_seconds`, `interrupt_message`, e o guard "agents.max_threads cannot be set when features.multi_agent_v2 is enabled" (v2 em desenvolvimento).

### 2.3 Custom agents (doc `codex/subagents`)

- Local: `~/.codex/agents/` (pessoal) e `.codex/agents/` (projeto); 1 TOML por agente.
- Obrigatórios: `name`, `description`, `developer_instructions`. Opcionais: `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `skills.config`, `nickname_candidates` + demais chaves de config.toml (agente = camada de config da sessão spawnada).
- Spawning: tool `spawn_agent` (+ `spawn_agents_on_csv` experimental com `report_agent_job_result`); acionado por pedido direto, AGENTS.md/skill, ou proativamente. Sem parâmetros formais → **argumentos são contrato textual** (o bloco `ARGS:` do dono é o workaround canônico e está correto).
- **Gotcha real**: issue openai/codex#14579 (0.114.0, fechada como bug) — agents de `.codex/agents/` do projeto não apareciam para `spawn_agent` (só via `-c`). Fechada, mas o framework deve ter um smoke-test de "agent do projeto visível" no bootstrap.

### 2.4 Skills (doc `codex/skills` → `learn.chatgpt.com/docs/build-skills`)

- **Discovery (precedência)**: (1) `$CWD/.agents/skills`, (2) diretórios pais até (3) `$REPO_ROOT/.agents/skills`, (4) `$HOME/.agents/skills`, (5) admin `/etc/codex/skills`, (6) built-ins (`skill-creator`, `plan`). Binário adiciona `"${CODEX_HOME:-$HOME/.codex}/skills"` (é onde estão as 19 skills locais) e skills de plugin. Conflito de nome: ambas ficam disponíveis (não faz merge). Symlinks suportados.
- **Formato**: `SKILL.md` com frontmatter mínimo `name` + `description` (description governa invocação implícita); recursos opcionais `agents/` (openai.yaml), `scripts/`, `references/`, `assets/`; recomendação <500 linhas.
- **`agents/openai.yaml`**: `interface` (`display_name`, `short_description`, `icon_small/large`, `brand_color`, `default_prompt`), `policy.allow_implicit_invocation` (default true), `dependencies.tools` (tipo `mcp` com `transport`/`url` — Codex instala/liga o MCP da skill automaticamente; feature `skill_mcp_dependency_install` stable true no binário).
- **Orçamento de contexto**: lista de skills usa no máx. 2% da janela (ou 8.000 chars); corpo carrega só quando selecionada (progressive disclosure ≈ Claude).
- **Controle**: `[[skills.config]] path=.../SKILL.md, enabled=false` no config.toml.

### 2.5 Hooks (doc `codex/hooks` → `learn.chatgpt.com/docs/hooks`) — A DESCOBERTA CENTRAL

- **Status**: `codex features list` no binário local → `hooks  stable  true` (habilitado por default). `plugin_hooks` aparece como "removed" (absorvido).
- **Fontes de hooks (todas carregadas se coexistirem)**: `~/.codex/hooks.json` ou `[hooks]` no `~/.codex/config.toml`; `<repo>/.codex/hooks.json` ou `[hooks]` no `.codex/config.toml` do repo (exige projeto trusted); plugins (`hooks/hooks.json`); managed dir enterprise (`[hooks] managed_dir`).
- **Formato** (JSON idêntico ao do Claude Code):

```json
{ "hooks": { "PreToolUse": [ { "matcher": "^Bash$",
    "hooks": [ { "type": "command", "command": "python3 guard.py", "timeout": 30 } ] } ] } }
```

  TOML equivalente: `[[hooks.PreToolUse]] matcher="^Bash$"` + `[[hooks.PreToolUse.hooks]] type="command" ...`. Só `type: "command"` executa hoje ("prompt" e "agent" são parseados e ignorados). `timeout` default 600s; `commandWindows` opcional.
- **Eventos**: `SessionStart` (matcher `source`: startup|resume|clear|compact), `SubagentStart` (matcher `agent_type`), `PreToolUse`, `PermissionRequest`, `PostToolUse` (matcher = tool name/regex, inclusive `mcp__server__.*`), `PreCompact`/`PostCompact` (matcher `trigger`: manual|auto), `UserPromptSubmit`, `SubagentStop`, `Stop`.
- **Contrato stdin/stdout**: input com `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `turn_id`; output com `continue`, `stopReason`, `systemMessage`, `suppressOutput` + `hookSpecificOutput` por evento (`permissionDecision: deny`, `updatedInput`, `additionalContext`, `decision.behavior: allow|deny`; "any deny wins"). **Exit 0 = ok, exit 2 + stderr = block** — o MESMO protocolo do Claude Code; strings do binário confirmam os wire-types (`SessionStartHookSpecificOutputWire`, `PreToolUseHookSpecificOutputWire`, ..., `stop_hook_active`).
- **Stop/SubagentStop podem bloquear e re-promptar**: `{"decision":"block","reason":"..."}` → reason vira novo prompt. Ou seja, **`completion-gate` e `ui-evidence-gate` do learnhouse são portáveis para Codex quase sem tradução**.
- **Trust model (diferença vs Claude)**: hooks não-managed exigem revisão/trust por **hash** (`/hooks` para inspecionar/confiar; hash muda → re-review); bypass pontual `--dangerously-bypass-hook-trust`. O bootstrap do framework precisa de um passo "trust dos hooks" no Codex.
- **Eventos que o Claude tem e o Codex NÃO**: `SessionEnd`, `Notification`, `PermissionRequest` existe no Codex mas não no Claude (ganho extra: automação de aprovação). Cobertura suficiente para todos os hooks atuais do harness (lessons-inject = SessionStart; diff-guard = PreToolUse; gates = Stop; throttle = SubagentStart).

### 2.6 Demais mecanismos relevantes

- **Prompts custom** (`~/.codex/prompts/*.md`, invocação `/prompts:nome`, placeholders `$1..$9`, `$ARGUMENTS`, named `$KEY`): **user-only e oficialmente deprecados em favor de skills** — o framework NÃO deve apostar neles; slash-commands Claude → skills no Codex.
- **Rules/approvals**: `~/.codex/rules/*.rules` com `prefix_rule(pattern=[...], decision="allow")` (Starlark; strings do binário confirmam runtime Starlark embutido) — análogo do allowlist `permissions.allow` do Claude.
- **Plugins**: `codex plugin` + `marketplaces`; strings mostram leitura de `.codex-plugin/plugin.json` **e `.claude-plugin/plugin.json`** — interop deliberada com plugins Claude (skills/hooks/MCP de plugin).
- **Memories**: feature `memories` **experimental, off por default** (config `generate_memories`, `use_memories`, `consolidation_model`...). Não confiar como base do lessons-loop hoje.
- **Goals**: feature `goals` stable true (strings: "goal continuation/steering"; `~/.codex/goals_1.sqlite`) — análogo parcial de execução longa; para o `/loop` do harness, o caminho robusto continua sendo cron externo + `codex exec` (headless não-interativo).
- **`codex exec`** aceita prompt por stdin, `-c` overrides, `--sandbox`, e sub-comando `review` — é o entry-point de automação (CI, loops, orquestração externa).

---

## 3. Matriz de paridade Claude × Codex (por peça do harness)

| Peça do harness | Claude Code | Codex (mecanismo equivalente) | Paridade / gap |
|---|---|---|---|
| Instruções de projeto | `CLAUDE.md` / `.claude/CLAUDE.md` | Cadeia `AGENTS.md` (global override → root→cwd, 1/dir, fallback filenames, cap `project_doc_max_bytes`) | ALTA. Sem `@import`; truncation silenciosa no cap → framework deve calcular tamanho e setar o cap. `CLAUDE.md` pode entrar via `project_doc_fallback_filenames` |
| Instruções globais do usuário | `~/.claude/CLAUDE.md` + rules | `~/.codex/AGENTS.md` (+ `AGENTS.override.md`) | ALTA |
| Hooks/guardas determinísticos | `settings.json` hooks (SessionStart, PreToolUse, PostToolUse, Stop, SubagentStop, UserPromptSubmit, PreCompact, SessionEnd, Notification) | **Nativo, stable**: `hooks.json`/`[hooks]` em `~/.codex` e `<repo>/.codex`; eventos SessionStart, SubagentStart, PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, UserPromptSubmit, SubagentStop, Stop; mesmo protocolo JSON/exit-2 | ALTA (novidade). Gaps: sem `SessionEnd`/`Notification`; só handler `command`; **trust por hash exige passo de bootstrap**; Stop bloqueante existe → completion-gate/ui-evidence-gate portáveis |
| Skills | `.claude/skills/`, plugins, Skill tool | **Nativo**: `.agents/skills` (walk-up), `~/.agents/skills`, `~/.codex/skills`, `/etc/codex/skills`, built-ins; `$nome` + implícito; `agents/openai.yaml`; `[[skills.config]]` | ALTA — mesmo SKILL.md serve os dois (prova: `~/.codex/skills` com skills de plugins Claude). Codex valida frontmatter keys (extras podem dar warning) |
| Subagents/custom agents | `.claude/agents/*.md` + Agent tool | `.codex/agents/*.toml` + `~/.codex/agents/`; `spawn_agent`/`spawn_agents_on_csv`; `[agents] max_threads/max_depth` | ALTA. Formato diverge (MD+frontmatter vs TOML) → framework gera os dois do config central. Args = contrato textual `ARGS:`. Histórico bug #14579 → smoke-test no bootstrap |
| Loop contínuo (`/loop`, loop.md) | skill `loop` + cron + Stop hooks | `codex exec` headless via cron/systemd + feature `goals` (parcial) | MÉDIA. Sem `/loop` nativo; o loop vira orquestração externa chamando `codex exec` |
| Memória/lessons (self-improvement) | auto-memory MEMORY.md + hook `lessons-inject.sh` (SessionStart) | `memories` = experimental/off. **Equivalente prático: hook SessionStart injetando `tasks/lessons.md` via `additionalContext`** + captura via prosa no AGENTS.md | MÉDIA→ALTA com hooks (injeção OK); geração/consolidação automática ainda é prosa |
| Wiki/docs lint (Karpathy) | scripts python + Stop hook + skill curator | Mesmos scripts (agnósticos) + hook Stop/PostToolUse Codex + skill em `.agents/skills` | ALTA (scripts são runtime-neutral) |
| Permissions/allowlist | `settings.json` `permissions.allow` | `~/.codex/rules/*.rules` (`prefix_rule`), `approval_policy`, `sandbox_mode`, `projects.trust_level` | MÉDIA. Shapes muito diferentes; framework traduz uma lista central para os dois formatos |
| Slash commands | `.claude/commands/*.md` | `~/.codex/prompts` (deprecado, user-only) → usar **skills** | BAIXA no mecanismo, ALTA na prática: comando → skill `$nome` |
| MCP servers | `.mcp.json` (projeto) | `[mcp_servers.*]` no config.toml (user; projeto se trusted); `codex mcp` | ALTA via geração: mesmo endpoint HTTP (`http://127.0.0.1:18114/mcp`) declarado nos dois formatos |
| Marketplace/plugins | `.claude-plugin/plugin.json` | `codex plugin` + marketplaces; **lê `.claude-plugin/plugin.json` também** | ALTA (interop nativa do lado Codex) |
| Verificação/DoD (prova-de-conclusao) | Stop hook `completion-gate` | Stop hook Codex com `decision:block` + scripts witness/ledger do agent-swarm como implementação | ALTA (novidade) |

## 4. O que SÓ é possível via prosa no AGENTS.md (limites duros restantes)

1. **Argumentos formais para skills/agents** — não existem em nenhum dos dois runtimes; o bloco `ARGS:` textual do dono é o padrão certo e deve ser preservado no framework.
2. **`SessionEnd`/`Notification` hooks** — inexistentes no Codex; qualquer lógica de fim-de-sessão vira prosa ou é aproximada com `Stop`/`SubagentStop`.
3. **Handlers de hook `prompt`/`agent`** — parseados mas ignorados; hook que "chama outro agente" no Codex hoje = `type: command` que roda `codex exec`.
4. **Consolidação automática de memória** (auto-memory do Claude) — `memories` experimental/off; capturar lição continua sendo instrução em prosa + arquivo versionado (`tasks/lessons.md`), com injeção via SessionStart hook.
5. **Semântica do council** (gates PLAN→PLAN_REVIEW→EXECUTION, sentinels, handoffs REPLAN/FIX) — é contrato de linguagem natural nos dois runtimes; hooks podem VALIDAR sentinels no Stop, mas o fluxo em si vive em SKILL.md/AGENTS.md.

## 5. Recomendações diretas para o plano do framework portátil

1. **Config central → geradores por superfície**: emitir `AGENTS.md` (com fallback `CLAUDE.md` via `project_doc_fallback_filenames` na direção inversa), `.codex/config.toml`, `.codex/agents/*.toml`, `.claude/agents/*.md`, `hooks.json` (Codex) + `settings.json.hooks` (Claude) do MESMO manifesto — os protocolos de hook são compatíveis o suficiente para 1 script servir os dois.
2. **Escrever hooks uma vez**: scripts shell/python neutros lendo o JSON comum (`hook_event_name`, `tool_input`...), registrados nos dois runtimes. Migrar os guards do learnhouse (lessons-inject→SessionStart, understand-diff-guard→PreToolUse, completion/ui-evidence-gate→Stop, subagent-throttle→SubagentStart) para o par.
3. **Skills como unidade canônica de comando**: todo slash-command do framework vira skill em `.agents/skills/` (lida por ambos: Codex nativo; Claude via cópia/symlink para `.claude/skills` no bootstrap) escrita no estilo dual-runtime do council (nomear o mecanismo por runtime, como SKILL.md Linhas 116/153/231).
4. **Bootstrap Codex precisa de 3 passos que o Claude não tem**: (a) `trust_level` do projeto no `~/.codex/config.toml`; (b) trust dos hooks (`/hooks`) — documentar/automatizar com `--dangerously-bypass-hook-trust` apenas em CI; (c) smoke-test de `spawn_agent` enxergando os agents do repo (regressão #14579).
5. **Dimensionar `project_doc_max_bytes` automaticamente** no bootstrap (soma dos AGENTS.md da cadeia + margem) — o default 32 KiB trunca silenciosamente; o learnhouse já precisou de 65536.
6. **Religar o contrato executável do agent-swarm aos hooks**: `verify_witness.py`/sentinel-check como Stop hook, `agent_swarm_ledger.py` como PostToolUse/SubagentStop hook — em vez de validação "local/manual" por disciplina.
7. **Atualizar a doc do dono**: AGENTS.md/CLAUDE.md do learnhouse (seção Council, sync 2026-07-06) foram escritos sob a premissa "Codex sem hooks/enforcement"; a premissa caiu no 0.144. Também corrigir o drift AGENTS.md×CLAUDE.md (§6 D[n] vs "5 perguntas").

## 6. Fontes

- Locais: paths citados acima; binário `~/.vscode-server/extensions/openai.chatgpt-26.707.31428-linux-x64/bin/linux-x86_64/codex` (v0.144.0-alpha.4; `--help`, `features list`, `strings`).
- Oficiais: [AGENTS.md](https://developers.openai.com/codex/guides/agents-md) · [Config reference](https://developers.openai.com/codex/config-reference) · [Subagents](https://developers.openai.com/codex/subagents) · [Hooks](https://developers.openai.com/codex/hooks) · [Skills](https://developers.openai.com/codex/skills) · [Custom prompts (deprecated)](https://learn.chatgpt.com/docs/custom-prompts) · [issue #14579](https://github.com/openai/codex/issues/14579) · [openai/skills](https://github.com/openai/skills).
