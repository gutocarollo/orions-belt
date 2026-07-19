# INVESTIGAÇÃO 4 — Superfície Nativa de Distribuição/Configuração do Claude Code

**Data**: 2026-07-17  
**Fonte**: Documentação oficial Claude Code (code.claude.com/docs)  
**Objetivo**: Avaliar o empacotamento nativo recomendado para um framework portátil de harness + hooks + skills + agents + templates

---

## 1. PLUGINS — O que podem empacotar e como

### 1.1 Escopo de componentes por plugin

Um **plugin** é um diretório self-contained que pode empacotar:

- **Skills** (`skills/` ou `commands/` dir) — instruções model-invocable (SKILL.md)
- **Agents** (`.claude/agents/*.md`) — custom subagents com system prompt e restrições de tools
- **Hooks** (`hooks/hooks.json`) — event handlers (SessionStart, PreToolUse, PostToolUse, Stop, etc.)
- **MCP servers** (`.mcp.json`) — integração com Model Context Protocol
- **LSP servers** (`.lsp.json`) — language servers para code intelligence
- **Monitors** (`monitors/monitors.json`) — background watchers que notificam Claude
- **Binários** (`bin/`) — executáveis adicionados ao PATH do Bash tool
- **Settings padrão** (`settings.json`) — valores de configuração aplicados à plugin ativação
- **Output styles** — custom rendering styles

**Manifest obrigatório**: `.claude-plugin/plugin.json` com campos:
```json
{
  "name": "unique-plugin-id",
  "description": "...",
  "version": "1.0.0",  # opcional; sem version, commit SHA é o pin
  "author": { "name": "..." }
}
```

### 1.2 Hooks em plugins — Sem tocar em settings.json do projeto

**SIM, possível**: Plugins registram hooks via `hooks/hooks.json` **sem modificar o projeto** `.claude/settings.json`:

- `hooks.json` é **descoberto automaticamente** quando o plugin é instalado
- Hooks do plugin **mesclam** com hooks do projeto (não sobrescrevem)
- Formato é idêntico ao de `settings.json` → `{ "hooks": { "SessionStart": [...], ... } }`
- Exemplo (Línea 451-463, plugins-reference.md):
```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        { "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/validate.sh" }
      ]
    }
  ]
}
```

### 1.3 Instalação por projeto vs global

**Escopos de instalação de plugins**:

1. **User** (global): `~/.claude/plugins/` — todos os projetos do usuário
2. **Project** (`.claude/settings.json` commited): compartilhado com o time
3. **Local** (`.claude/settings.local.json`, gitignored): pessoal só este repo
4. **Managed** (Admin-deployed): IT força plugin enable/disable para toda org
5. **Plugin marketplace** (`extraKnownMarketplaces`): repositório central (GitHub, GitLab, etc.)

**Instalação via CLI**:
```bash
/plugin install plugin-name@marketplace-name
/plugin marketplace add owner/repo  # GitHub shorthand
/plugin marketplace add ./local-path  # local testing
```

---

## 2. SETTINGS — Hierarquia e merging

### 2.1 Hierarquia (alta para baixa prioridade)

1. **Managed** (não pode ser overridado) — IT-deployed
2. **Command-line args** (`--plugin-dir`, `--setting-sources`)
3. **Local** (`.claude/settings.local.json`, gitignored)
4. **Project** (`.claude/settings.json`, commited)
5. **User** (`~/.claude/settings.json`)

### 2.2 Coexistência plugins + settings

- **Plugins declarados em settings**: `"enabledPlugins": { "my-plugin": true }`
- **Hooks de settings + hooks de plugins = MERGE** (não override)
- Exemplo: ambos `settings.json` e `plugin/hooks.json` têm PostToolUse → ambos rodam
- **Conflito de skills**: plugin skills são namespaced (`/plugin-name:skill`), nunca conflitam com projeto
- **Conflito de agentes**: agente do projeto **sobrescreve** agente de plugin com mesmo nome

### 2.3 Estrutura de settings.json

```json
{
  "permissions": {
    "allow": ["Bash(npm run lint)", "Read(~/.zshrc)"],
    "deny": ["Bash(curl *)", "Read(./.env)"]
  },
  "env": { "CLAUDE_CODE_ENABLE_TELEMETRY": "1" },
  "enabledPlugins": { "my-plugin": true },
  "extraKnownMarketplaces": { "company-tools": { "source": {...} } },
  "hooks": { "SessionStart": [...] }
}
```

---

## 3. SKILLS — Descoberta e frontmatter

### 3.1 Hierarquia de descoberta

Skills carregam em ordem (primeira instância vence):

1. **Plugin skills** (se plugin habilitado) — namespace `/plugin:skill`
2. **Project skills** (`.claude/skills/SKILL_NAME/SKILL.md`)
3. **User skills** (`~/.claude/skills/SKILL_NAME/SKILL.md`)
4. **Nested skills** (`.claude/skills/` em subdir) — prefix `subdir:skill`
5. **Bundled skills** (built-in: `/code-review`, `/debug`, `/loop`, `/batch`)

**Descoberta on-demand**: quando Claude lê arquivo em subdiretório, carrega skills daquele `.claude/skills/`.

### 3.2 Frontmatter (YAML entre `---`)

```yaml
---
name: my-skill                      # display name (fallback: directory name)
description: "What it does"         # quando Claude usa — RECOMENDADO
when_to_use: "trigger phrases"      # appended to description
disable-model-invocation: true      # só manual (/skill-name), não auto
user-invocable: false               # só Claude, não aparece em /menu
allowed-tools: "Read Grep Bash"     # pre-approve tools this turn
disallowed-tools: "Bash"            # remove tools while skill active
model: "claude-opus-4-1"            # override session model
effort: "high"                       # override effort level
context: fork                        # run in subagent (isolated context)
agent: "Explore"                    # which subagent type (Explore, Plan, general-purpose)
paths: "src/**/*.ts"                # glob — skill só carrega p/ esses files
shell: "bash"                       # bash (default) ou powershell
arguments: [issue, branch]          # named positional args p/ $issue, $branch
hooks: { "PreToolUse": [...] }      # lifecycle hooks deste skill
---

Instruções aqui...
Suporte a substitutions: $ARGUMENTS, $0, $1, ${CLAUDE_PROJECT_DIR}, ${CLAUDE_SKILL_DIR}
Suporte a injeção dinâmica: !`git diff HEAD` (roda antes Claude ver)
```

### 3.3 Locais onde skills vivem

| Local | Escopo | Path |
|-------|--------|------|
| Enterprise | Org inteira | Managed-deployed |
| Personal | Todos projetos | `~/.claude/skills/SKILL_NAME/` |
| Project | Este repo | `.claude/skills/SKILL_NAME/` |
| Plugin | Onde plugin habilitado | `plugin-root/skills/SKILL_NAME/` |
| Nested (monorepo) | Subdir específico | `packages/web/.claude/skills/SKILL_NAME/` |

---

## 4. AGENTS — Definição em .claude/agents/

### 4.1 Formato e descoberta

- **Path**: `.claude/agents/AGENT_NAME.md`
- **Escopo**: project (`.claude/agents/`) ou user (`~/.claude/agents/`)
- **Naming**: kebab-case
- **Invocação**: `@agent-name` em chat, ou Task tool para subagent anônimo

### 4.2 Frontmatter de agente

```yaml
---
name: security-reviewer
description: Reviews code for security vulnerabilities
model: "claude-opus-4-1"            # override session model
tools: "Read Grep Bash"             # restrict to these tools (default: all)
---

You are a security-focused code reviewer...
```

- **Sem tools field** → herdas todas as tools da session
- **Tools field** → whitelist de tools (RBAC stricto)
- **Custom system prompt** (markdown body) → aplicado em lugar do prompt padrão
- **Model override** → possível, p.ex. usar claude-3-5-sonnet só neste agent

### 4.3 Subagent vs agente de plugin

- **Subagent** (`.claude/agents/my-agent.md`) → custom agent invocável via `/Task Agent:my-agent`
- **Plugin agent** → agente dentro de plugin, namespaced
- **Conflito**: agente de projeto com mesmo nome sobrescreve agente de plugin

---

## 5. MEMÓRIA — Hierarquia CLAUDE.md e auto-memory

### 5.1 Hierarquia de CLAUDE.md

Load order (raiz para específico, últimas sobrescrevem):

1. **Managed** (`/etc/claude-code/CLAUDE.md` or plist equivalent) — org-wide
2. **User** (`~/.claude/CLAUDE.md`) — pessoal, todos projetos
3. **Project** (`./CLAUDE.md` ou `./.claude/CLAUDE.md`) — team-shared
4. **Local** (`./CLAUDE.local.md`, gitignored) — pessoal, este repo
5. **Nested** (`.claude/CLAUDE.md` em subdir, on-demand) — quando abre arquivo naquele dir

**Sintaxe de import**: `@path/to/file` expande inline (recursivo até depth 4)

### 5.2 Auto-memory (machine-local)

- **Path**: `~/.claude/projects/<project-slug>/memory/`
- **Índice**: `MEMORY.md` (até 200 linhas ou 25KB carregadas por sessão)
- **Topic files**: `debugging.md`, `api-conventions.md`, etc. (on-demand)
- **Escopo**: compartilhado entre worktrees do mesmo git repo
- **Mecanismo**: Claude escreve notes (sem ser pedido) quando aprende algo reutilizável

**Toggle**: `/memory` command ou `"autoMemoryEnabled": false` em settings.json

### 5.3 Organização em monorepo

- `.claude/rules/` para rules path-specific (YAML frontmatter `paths: "src/**/*.ts"`)
- Nested `.claude/CLAUDE.md` em pacotes (load on-demand quando abre arquivo naquele dir)
- Exclusão: `claudeMdExcludes` glob pattern para skip CLAUDE.md de outros times

---

## 6. MARKETPLACE PLUGIN — Distribuição

### 6.1 Marketplace.json

**Path**: `.claude-plugin/marketplace.json` no repo

```json
{
  "name": "my-marketplace",
  "owner": { "name": "Team Name", "email": "..." },
  "plugins": [
    {
      "name": "plugin-id",
      "source": "./plugins/plugin-id",  # local path, github, url, npm
      "description": "...",
      "version": "1.0.0",                # optional; commit SHA se omitido
      "author": { "name": "..." }
    }
  ]
}
```

### 6.2 Plugin sources (5 tipos)

| Tipo | Sintaxe | Notas |
|------|---------|-------|
| Relative path | `"./plugins/my-plugin"` | Resolvem vs marketplace root |
| GitHub | `{ "source": "github", "repo": "owner/repo", "ref?", "sha?" }` | Public/private com auth |
| Git URL | `{ "source": "url", "url": "https://...", "ref?", "sha?" }` | GitLab, Bitbucket, etc. |
| Git subdir | `{ "source": "git-subdir", "url": "...", "path": "...", "ref?", "sha?" }` | Sparse clone (monorepo) |
| npm package | `{ "source": "npm", "package": "@org/plugin", "version?", "registry?" }` | Public/private registry |

### 6.3 Versioning e updates

- **Explícito** (`"version": "1.0.0"`): usuário só atualiza quando você bump
- **Implícito** (sem `version`): commit SHA = versão, cada commit = novo version
- **Release channels**: duas marketplaces apontam p/ refs diferentes (stable vs latest)
- **Updates**: `/plugin marketplace update <name>` ou background auto-update
- **Private repos**: auth via git credential helper ou SSH ssh-agent

### 6.4 Instalação de marketplace

```bash
/plugin marketplace add owner/repo@main                # GitHub
/plugin marketplace add https://example.com/plugins    # URL  
/plugin marketplace add ./local-path                   # local
claude plugin marketplace add <source> --scope project # persist em .claude/settings.json
```

---

## 7. LIMITAÇÕES DURAS — Por via de distribuição

### 7.1 Plugin como solução

**O QUE PODE**:
- ✅ Empacotar skills + hooks + agents + MCP + LSP + monitors
- ✅ Carregar sem modificar `.claude/settings.json` do projeto (plugin.json é auto-discovered)
- ✅ Versionar e distribuir via marketplace (GitHub, npm, git, URL)
- ✅ Auto-updates e rollback
- ✅ Namespace skills (`/plugin:skill`) para evitar conflitos
- ✅ Pre-populate via `CLAUDE_CODE_PLUGIN_SEED_DIR` (CI/CD, containers)
- ✅ Managed restrictions (`strictKnownMarketplaces` em org admin settings)

**O QUE NÃO PODE**:
- ❌ Forçar settings obrigatórias (plugins têm `settings.json` padrão, mas projeto pode override)
- ❌ Proteger conteúdo de skills contra cópia (tudo é plaintext)
- ❌ Referenciar arquivos fora do plugin dir (plugin é cached em `~/.claude/plugins/cache/`)
- ❌ Modificar estrutura de permissões ou CLAUDE.md do projeto (read-only)
- ❌ Executar hooks em projeto onde plugin NÃO é habilitado
- ❌ Atualizar automaticamente em máquinas sem rede (seed-dir é read-only)

### 7.2 Standalone (.claude/) como solução

**O QUE PODE**:
- ✅ Skills, hooks, agents no projeto (100% controle local)
- ✅ CLAUDE.md, rules, custom MCP servers
- ✅ Compartilhar via git commit (team-shared)
- ✅ Modificar on-the-fly sem reload (live change detection)
- ✅ Máxima flexibilidade (sem namespace, sem cache)

**O QUE NÃO PODE**:
- ❌ Distribuir facilmente (copy-paste ou git clone)
- ❌ Versionar independentemente (acoplado ao repo)
- ❌ Reusar em N projetos sem duplicação
- ❌ Ter múltiplas versões coexistindo

### 7.3 Híbrido (Plugin + Standalone)

**Padrão recomendado**:
- Plugin = código canônico + hooks + agents reutilizáveis
- `.claude/` = customizações locais, overrides, configs project-specific

---

## 8. COMPARAÇÃO: understand-anything vs hookify

### 8.1 understand-anything

**Distribuído como**: Plugin no marketplace oficial Anthropic
- **Marketplace**: `github.com/Egonex-AI/Understand-Anything`
- **Install**: `/plugin install understand-anything@claude-plugins-official`
- **Conteúdo**:
  - Skills: `/understand`, `/understand-explain`, `/understand-chat`, `/understand-dashboard`, `/understand-diff`, `/understand-onboard`, `/understand-domain`, `/understand-knowledge`
  - Agents: `understand-architecture-analyzer`, `understand-domain-analyzer`, `understand-file-analyzer`, etc.
  - MCP servers: via `.mcp.json` (Postgres, codebase scanner)
  - Sem hooks (não precisa)

**Vantagens**:
- Totalmente self-contained
- Zero projeto customização
- Versionamento independente
- Updates automáticos

### 8.2 hookify

**Distribuído como**: Plugin oficial Anthropic
- **Marketplace**: `github.com/anthropics/claude-plugins-official` (subdir `hookify/`)
- **Install**: `/plugin install hookify@claude-plugins-official`
- **Conteúdo**:
  - Skills: `/hookify:help`, `/hookify:configure`, `/hookify:list`, `/hookify:hookify`, `/hookify:writing-rules`
  - Agents: `hookify:conversation-analyzer`
  - Hooks: **SIM** — hookify próprio tem hooks que analisam conversation e propõem novas rules
  - Outputs: custom rendering para rules

**Diferença**: hookify NECESSITA hooks para sua própria lógica (análise adversária pós-turn); understand-anything pura orchestração de skills/agents sem precisa de hooks.

---

## 9. CONCLUSÃO — Empacotamento recomendado para harness portátil

### 9.1 Recomendação final: **PLUGIN (com fallback standalone)**

Para transformar harness-wiki num framework portátil parametrizável:

**CAMINHO PRIMARY (recomendado)**:
```
harness-portable/
├── .claude-plugin/
│   ├── plugin.json                    # manifest: name, version, author
│   └── marketplace.json               # future: distribuição própria
├── skills/
│   ├── harness-init/SKILL.md
│   ├── harness-validate/SKILL.md
│   ├── harness-templates/SKILL.md
│   └── [outros skills reutilizáveis]
├── agents/
│   ├── harness-architect.md           # system prompt custom
│   ├── harness-auditor.md
│   └── harness-code-reviewer.md
├── hooks/
│   └── hooks.json                     # Pre/Post tool hooks, Stop gate
├── .mcp.json                          # MCP servers integrados (Postgres, git, etc)
├── monitors/
│   └── monitors.json                  # background watchers
├── settings.json                      # default permissions, env vars
└── templates/                         # boilerplate CLAUDE.md, config samples
```

**Instalação**:
```bash
/plugin install harness-portable@[marketplace]
# Ou local development:
claude --plugin-dir ./harness-portable
```

**Vantagens**:
- Zero modificação projeto `.claude/settings.json` necessária
- Hooks rodam automaticamente (pre/post tool, stop gate)
- Skills e agents namespaced (`/harness-portable:init`, `@harness-auditor`)
- Versioning e updates independentes
- Distribuição via marketplace (GitHub, npm)
- Reutilizável em N projetos
- Pre-populate em CI/CD via seed-dir

### 9.2 Fallback: standalone `.claude/` em projeto piloto

```
learnhouse/.claude/
├── skills/
│   └── harness-init/SKILL.md
├── agents/
│   └── harness-auditor.md
├── hooks/
│   └── hooks.json
└── CLAUDE.md                          # import @harness-portable/config.md
```

**Quando**:
- Projeto piloto que quer customizar on-the-fly
- Antes da plugin estar pronto (development)
- Local overrides sem reflex no plugin central

**Limite**: não reutiliza em outros projetos sem duplicação.

### 9.3 Configuração central

**Parametrização via config file**:
```json
// harness-portable/config.json (ou .env, TOML)
{
  "name": "harness-portable",
  "version": "1.0.0-alpha",
  "git_repos": [
    { "repo": "gutocarollo/harness-wiki", "version": "main" },
    { "repo": "gutocarollo/agent-swarm", "version": "main" },
    { "repo": "gutocarollo/guto-wiki", "version": "main" }
  ],
  "hooks": {
    "enablePreCompactValidation": true,
    "enablePostToolUseAudits": true
  },
  "skills": {
    "includeBundledExamples": true,
    "templateDir": "./templates"
  }
}
```

**Consumo**: Skills e agentes usam `!`bash injection`` para ler e parametrizar templates.

---

## 10. Resumo executivo — Limitações vs Vias

| Critério | Plugin | Standalone | Híbrido |
|----------|--------|-----------|---------|
| **Reutilização N projetos** | ✅ Sim (install) | ❌ Não (copy-paste) | ✅ Sim |
| **Versioning** | ✅ Independente | ❌ Acoplado repo | ✅ Sim |
| **Hooks automáticas** | ✅ Sim | ✅ Sim | ✅ Sim |
| **Zero projeto modif** | ✅ Sim | ❌ Não | ❌ Parcial |
| **Customização local** | ⚠️ Via settings override | ✅ Sim | ✅ Sim |
| **Distribuição** | ✅ Marketplace + npm | ❌ Git clone | ✅ Sim |
| **Manutenção** | ✅ Uma fonte | ❌ Múltiplas copies | ✅ Central + local |

**DECISÃO FINAL**: **Plugin PRIMARY + Standalone SECONDARY para customização.**

Isso alinha com como **understand-anything** (plugin puro) e **hookify** (plugin com agents + hooks) funcionam — ambos são distribuidores como plugins oficiais Anthropic, zero duplicação, versioning centralized, zero modificação projeto.

---

## 11. Próximos passos de implementação

1. **Criar plugin scaffold**: `harness-portable/.claude-plugin/plugin.json`
2. **Migrate skills**: `skills/harness-init`, `skills/harness-audit`, etc. (de `.claude/skills/` LearnHouse)
3. **Port agentes**: `agents/harness-architect.md`, etc. (de `.codex/agents/`)
4. **Consolidar hooks**: `hooks/hooks.json` (de `.claude/settings.json` + `.claude/hooks/`)
5. **Template docs**: `.claude/CLAUDE.md`, `.claude/rules/` exemplos
6. **Config central**: `config.json` (parametrização, git repo refs, feature flags)
7. **Teste local**: `claude --plugin-dir ./harness-portable`
8. **Marketplace**: GitHub repo `gutocarollo/harness-portable`, `.claude-plugin/marketplace.json`
9. **Distribution**: `/plugin install harness-portable@...` ou npm (futura)
10. **Seed-dir**: container image pre-population (EasyPanel prod deployment)

