# Investigação 6 — Soluções maduras para "instalar/auto-configurar um kit de arquivos em qualquer projeto" (LEI ZERO)

Data: 2026-07-17 · Escopo: alimentar o PLANO do framework portátil (harness-wiki + guto-wiki + agent-swarm → framework instalável, config central, update, Claude Code + Codex).
Método: leitura real de arquivos locais (harness-wiki, plugin understand-anything instalado) + pesquisa web (docs oficiais Copier, repo spec-kit, chezmoi FAQ, cruft, agentskills.io ecosystem).

---

## 0. O problema exato que o instalador precisa resolver (derivado do inventário real)

O "kit" a instalar é o conteúdo espelhado em `/home/augusto/code/harness-wiki/sources/` (paths originais preservados — `README.md` Linha 14):

| Classe de arquivo | Exemplos reais no kit | Característica de instalação |
|---|---|---|
| Hooks executáveis + wiring | `sources/.claude/hooks/*`, `sources/.claude/settings.json` (17 ligações evento→script, `manifest.json` Linha 12) | Precisam de MERGE em `settings.json` existente OU de um mecanismo que os carregue sem tocar no settings do usuário |
| Regras hookify | 12 arquivos `sources/.claude/hookify.*.local.md` | Cópia simples, mas 5 são `qq-prod-*` (específicos do cliente) — precisam de parametrização/exclusão condicional |
| Skills | `sources/.claude/skills/`, e no learnhouse também `.agents/skills/` (council p/ Codex) | Formato SKILL.md — hoje um padrão aberto cross-agent (ver §5c) |
| Wiki Karpathy | `SCHEMA.md`, `log.md`, `scripts/docs-wiki-lint.py`, `ref-integrity.py` | Arquivos "living" que o projeto-alvo passa a EVOLUIR — update do template não pode sobrescrever (`_skip_if_exists`) |
| Config por agente | `sources/.codex/config.toml`, `sources/.codex/agents/*.toml`, `CLAUDE.md`/`AGENTS.md` | Multi-agente: mesmo conteúdo, materializações diferentes por runtime |
| Loops/contratos | `sources/.claude/loop.md`, contracts, banlist | Banlist e loop têm conteúdo cliente-específico (ver `SENSITIVE.md`) — template com variáveis |

Parâmetros que hoje estão HARDCODED no kit (evidência: `manifest.json` Linhas 34, 43-45 — portas 1338/3009/5433; capítulo 07 — guardas `qq-prod-*`; `SENSITIVE.md` — nomes/URLs de cliente): portas da stack, nomes de serviço/produção, paths de evidência, banlist, denominadores de gates. **Isso é exatamente o caso de uso de um answers-file central.**

Requisito de UX declarado pelo dono (analogia understand-anything): "se adapta, entende o projeto e se auto-configura". Tratado aqui como requisito de UX (uma fase de adaptação semântica pós-cópia), não como mandato de implementação.

---

## 1. Candidato (a) — Copier (copier-org/copier) — **o motor de cópia+update**

Fonte: docs oficiais `copier.readthedocs.io` (stable), páginas *updating* e *configuring* (fetch 2026-07-17).

**Mecânica que nos importa:**
- `copier.yml` no repo-template define **perguntas** (tipos `bool/int/str/json/yaml/path`, choices, `when:` condicional, validators, defaults dinâmicos em Jinja) — é o "arquivo de config central" na origem.
- **`.copier-answers.yml` gravado NO projeto-alvo** (nome customizável via `_answers_file` — pode ser `.harness/answers.yml`): registra respostas + `_commit` (tag do template usada). É a materialização exata do requisito "arquivo de config central parametrizável" + a chave do update.
- **`copier update` = o diferencial vs cookiecutter**: relê as respostas, regenera um projeto fresco na versão nova do template, extrai o diff das customizações locais ("smart diff"), aplica o template novo e **re-aplica o diff local** (merge 3-vias); conflitos viram markers inline (`--conflict inline`, default) ou `.rej`. Requisitos: template git com **tags** (PEP 440), projeto-alvo git, working tree limpa.
- Recursos que mapeiam 1:1 no nosso kit: `_skip_if_exists` (lessons.md, log.md, loop.md — criados uma vez, nunca sobrescritos no update), `_exclude`, **Jinja em paths** (gera `.codex/` só se `use_codex=true`; omite guardas qq-prod-* se `client_guards=false`), `_tasks` (pós-geração: `chmod +x hooks`, `git config core.hooksPath .githooks`), `_migrations` (breaking changes versionadas entre tags), múltiplos templates no mesmo projeto com answers-files distintos (permite separar "harness-core" de "wiki-karpathy" como templates independentes).
- Trust model: `_tasks`/`_migrations` exigem `--trust` — aceitável (kit próprio).

**§9.1:** Delta de qualidade: é a ÚNICA opção da lista com update 3-vias que preserva customização local — cookiecutter puro não tem, cruft está de facto abandonado (§2), spec-kit faz stomp+merge manual (§3). Delta de custo: 1 dependência Python de tooling (`uvx copier` / pipx — zero dep no projeto-alvo em runtime), curva baixa-média (copier.yml + Jinja; ~1 dia para templatizar o kit atual), obrigação de disciplina de tags no repo-template. Breakeven: ≥2 projetos-alvo OU 1 ciclo de update do kit já paga (re-instalar na mão o kit de ~40 arquivos e re-aplicar customizações é horas por projeto). Condição de não-adoção: se decidirmos que o framework será SÓ um plugin Claude Code (sem materializar arquivos no repo) — mas isso mataria o suporte Codex e a wiki (que é do repo por natureza), então improvável.

**Aderência ao nosso caso: alta (9/10).** Único gap: copier não resolve "entender o projeto" (respostas semânticas) nem distribui hooks vivos para o Claude sem materializar arquivos — resolvidos pelas outras camadas do híbrido (§7).

## 2. Candidato (b) — Cookiecutter (+ cruft) — baseline, descartado

- Cookiecutter: geração one-shot; **não existe caminho de update** — mudou o template, cada projeto re-porta na mão.
- cruft (o "update para cookiecutter"): grava `.cruft.json` com commit-hash e faz diff template-velho→template-novo; porém relatos públicos apontam projeto **sem manutenção ativa** ("not developed anymore… full of issues and pull requests", usuários migrando para copier) e o modelo depende de skip-lists manuais.
- **§9.1:** delta de qualidade NEGATIVO vs copier em tudo que importa (update, condicionais, migrations); custo igual (Python). Não-adoção: sempre, exceto se já existisse template cookiecutter legado (não existe). **Descartado.**

## 3. Candidato (c) — GitHub spec-kit — **a arquitetura de referência multi-agente (portar padrões, não depender)**

Fonte: `github.com/spec-kit` README + docs/upgrade.md + discussions #331/#879 + issue #1436 (fetch/search 2026-07-17).

**Como resolve exatamente o nosso problema multi-agente:**
- CLI `specify init` com flag por agente (hoje `--integration <agent>`; historicamente `--ai`), suportando 30+ agentes (Claude, Codex, Copilot, Gemini, Cursor…). Para cada agente, materializa o MESMO comando no formato nativo daquele runtime: `.claude/commands/*.md` para Claude, `.codex/prompts/*` para Codex, etc. — **fonte única de template, matriz de renderização por agente**. Este é o padrão a portar para o nosso par Claude+Codex.
- `specify init --here` (brownfield: instala no diretório atual, projeto existente) e `--force` para re-aplicar.
- **Stack de resolução de templates em runtime** com precedência: `.specify/templates/overrides/` (projeto) → presets → extensions → core defaults. Padrão elegante para "o projeto customiza sem forkar o kit".
- `.specify/memory/constitution.md` = análogo direto do nosso CLAUDE.md/SCHEMA.md como "constituição" instalada.
- **Extensão `/speckit.brownfield-bootstrap`** (issue #1436): comando LLM que analisa o projeto existente e adapta os templates genéricos à arquitetura/stack real — **é exatamente o requisito de UX "se adapta e se auto-configura" do dono, já resolvido por terceiros como uma fase LLM pós-init.** Validar e portar o desenho.
- **Ponto fraco decisivo — update:** o caminho oficial de atualização de um projeto já inicializado é `specify init --here --force` (re-stomp) com **backup manual** de `memory/constitution.md` e `templates/` e merge manual depois (docs/upgrade.md, discussion #879). Sem answers-file, sem merge 3-vias. Inferior ao copier precisamente no nosso requisito nº1.

**§9.1:** como DEPENDÊNCIA: delta de qualidade baixo (workflow SDD ≠ nosso harness; update fraco), custo de acoplamento alto → **não adotar como dependência**. Como REFERÊNCIA DE DESIGN: delta de qualidade alto e custo zero → **portar**: (1) flag `--agent claude,codex` com matriz de renderização; (2) `--here` brownfield como modo default; (3) stack de overrides; (4) fase brownfield-bootstrap LLM. Condição de não-portar: nenhuma.

## 4. Candidato (d) — chezmoi / dotfile managers — descartado com fonte

FAQ oficial do chezmoi: operar fora do home dir é possível via `--destination`, "**but this usage is extremely strongly discouraged**"; para além de um punhado de arquivos fora do target, a própria doc manda usar outra ferramenta. Design = 1 source state → 1 destination por máquina; nosso caso = N projetos independentes, cada um com respostas próprias e ciclo de update próprio. O templating go-template + `chezmoi.toml` não compensa lutar contra o modelo de destino único. **§9.1:** custo (dep Go + modelo torcido) > qualquer delta; não-adoção: sempre para este caso. Único conceito aproveitável: separação "source state versionado / target aplicado / data de máquina" — que o copier já dá com answers-file.

## 5. Candidato (e) — Mecanismos nativos dos agentes

### 5a. Claude Code plugin + marketplace (understand-anything = o modelo vivo; superpowers/obra = marketplace maduro)

Evidência local (plugin instalado nesta máquina):
- Estrutura: `~/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/` com `.claude-plugin/plugin.json` (name/version/homepage), `skills/` (8 skills), `hooks/hooks.json`, `agents/`. Marketplace = repo git com `.claude-plugin/marketplace.json` listando plugins (`~/.claude/plugins/marketplaces/understand-anything/.claude-plugin/marketplace.json`).
- **O padrão de auto-configuração por projeto** (`hooks/hooks.json`): o plugin é GLOBAL, mas os hooks SessionStart/PostToolUse são condicionais à existência de estado local do projeto — `[ -f .understand-anything/config.json ] && grep -q '"autoUpdate".*true' …` — i.e., **plugin inerte até o projeto ser inicializado; toda a parametrização vive num diretório de estado do projeto** (`.understand-anything/{config.json,meta.json,knowledge-graph.json}`), escrito pelo comando `/understand` (flags `--auto-update`, `--language` gravadas no config.json — `skills/understand/SKILL.md` Linhas 15-19). O hook detecta staleness comparando `meta.json.gitCommitHash` vs `git rev-parse HEAD` e INSTRUI o agente a se atualizar ("You MUST read … and execute") — auto-manutenção via prompt-injection de hook.
- Bônus do mesmo SKILL.md (Linha ~68+): resolução de plugin-root multi-instalação com fallback para `~/.agents/skills/understand` (symlink universal) — o próprio understand-anything já se distribui também FORA do ecossistema de plugin Claude, via dir de skills universal.
- Vantagem estrutural do plugin para HOOKS: `hooks.json` do plugin é carregado pelo Claude Code sem tocar no `settings.json` do usuário — **elimina o problema de merge de settings.json**, o ponto mais frágil de uma instalação por cópia de arquivos.
- superpowers (obra): exemplo maduro de marketplace comunitário — `/plugin marketplace add obra/superpowers-marketplace` + `/plugin install superpowers@superpowers-marketplace`; skills auto-disparam por descrição. Modelo de distribuição/atualização (plugin update por versão git) comprovado.
- **Limite:** plugin Claude Code não instala NADA para o Codex, não materializa a wiki no repo, e hooks de plugin são globais (rodam em todo projeto — daí a necessidade do gating por config local, como o understand-anything faz).

### 5b. Codex — sem sistema de plugin

Evidência local: `harness-wiki/sources/.codex/{config.toml,agents/}` + AGENTS.md. Codex consome ARQUIVOS NO REPO (`.codex/agents/*.toml`, `AGENTS.md`, `.agents/skills/`). Logo a perna Codex EXIGE materialização de arquivos → exige o motor de scaffolding (copier), não há atalho de plugin.

### 5c. Agent Skills = padrão aberto cross-agent (mudança de cenário a favor do nosso plano)

SKILL.md foi publicado pela Anthropic como padrão aberto em agentskills.io (dez/2025) e é hoje suportado por ~40 produtos, **incluindo OpenAI Codex**, Copilot, Cursor, Gemini CLI (levantamento jun/2026). Consequência arquitetural: **as skills são a camada naturalmente compartilhada Claude+Codex** (um diretório de skills serve os dois runtimes); o problema multi-agente se reduz a (i) hooks (só Claude tem), (ii) commands/prompts (formatos distintos), (iii) config (`settings.json` vs `config.toml`) — exatamente o que a matriz de renderização estilo spec-kit resolve.

## 6. Candidato (f) — outros (yeoman, nx generators, npx create-*)

- **yeoman**: ecossistema JS datado, sem answers-file/update comparável ao copier; nada agrega.
- **nx generators**: excelentes para monorepos nx (geração + `nx migrate` com migrações), mas acoplados ao workspace nx — nosso alvo é "qualquer projeto". Não.
- **npx create-***: padrão one-shot sem update; útil só como UX de bootstrap (`uvx`/`npx harness init` como wrapper fino sobre copier é válido). Nenhum vira dependência.

---

## 7. VEREDITO — Arquitetura de instalação recomendada: HÍBRIDA em 3 camadas

**Camada 1 — Motor de arquivos: Copier (adotar como dependência de tooling).**
Repo-template único (a unificação dos 3 repos) com `copier.yml`; answers-file renomeado para algo como `.harness/answers.yml` (`_answers_file`) = **o arquivo de config central pedido pelo dono**, versionado no projeto-alvo. Jinja em paths para a matriz por agente (`use_claude`, `use_codex`) e por módulo (`wiki`, `council`, `gates`, `loops` — perguntas bool com `when:`); `_skip_if_exists` para living files (lessons.md, log.md, loop.md, banlist); `_tasks` para chmod/hooksPath; `_migrations` + tags PEP 440 para breaking changes; `copier update` como caminho oficial de atualização com preservação de customizações (merge 3-vias). Portar do spec-kit: modo brownfield default (`--here`), stack de overrides do projeto (`<kit>/templates/overrides/` vence core) e o conceito de constituição instalada.

**Camada 2 — Integração viva nos runtimes.**
Skills no formato Agent Skills (SKILL.md) num diretório compartilhado — servem Claude E Codex sem duplicação (§5c). Hooks: materializados no repo via copier COM parametrização lida de `.harness/answers.yml`/config (hooks genéricos + config local, padrão understand-anything §5a) — assim o mesmo hook script serve qualquer projeto e o `copier update` atualiza a lógica sem tocar nos parâmetros. Wiring no `settings.json`: gerado pelo copier quando não existe; quando existe, merge assistido na Camada 3 (ou, evolução futura, empacotar os hooks genéricos como plugin Claude com `hooks.json` próprio + marketplace `gutocarollo/…`, que elimina o merge — decisão adiável; começar repo-native mantém paridade Claude/Codex e 1 só mecanismo de update).

**Camada 3 — Configurador semântico LLM (o requisito de UX "understand-anything").**
Um comando/skill `harness-init` (instalado pela própria Camada 1) que roda DEPOIS do `copier copy`: escaneia o projeto (stack, portas, scripts, package manager, serviços), propõe/preenche as respostas (copier aceita `--data key=value` — o LLM pode responder o questionário programaticamente), faz o merge de `settings.json`/`AGENTS.md` preexistentes e adapta conteúdo semântico (banlist, guardas de produção, exemplos da wiki) ao domínio do projeto. Precedente externo direto: `/speckit.brownfield-bootstrap` (spec-kit issue #1436); precedente interno: `/understand` gravando `.understand-anything/config.json`. Estado da adaptação gravado no answers-file/config → o `copier update` posterior não a perde.

**Fluxo do usuário final:** `uvx copier copy gh:gutocarollo/<framework> . --trust` (ou wrapper `harness init`) → abrir o agente → `/harness-init` completa a auto-configuração → futuras versões: `copier update`.

**Por que não alternativas puras:** plugin-only quebra Codex e wiki-no-repo; spec-kit-style-only tem update por stomp; copier-only não cumpre a UX de auto-adaptação nem o carregamento vivo de hooks. O híbrido usa cada mecanismo no seu ponto forte, com UMA fonte de verdade (repo-template) e UM registro de estado por projeto (answers-file + config).

## 8. Gaps do harness-wiki local vs este estado da arte

1. Nenhum instalador: `sources/` é espelho estático de leitura ("paths preservados", README Linha 14) — não há script/CLI que aplique o kit em outro projeto.
2. Nenhuma parametrização: portas (1338/3009/5433), nomes qq-prod, banlist e URLs estão literais (manifest.json Linhas 43-45; SENSITIVE.md) — zero variáveis/template.
3. Nenhum caminho de update: sem versão de template, sem answers-file, sem migrations (manifest `"version": "1.0.0"` é do conteúdo editorial, não de um template instalável).
4. Nenhuma matriz multi-agente: `.claude/` e `.codex/` coexistem como cópias literais do learnhouse, sem fonte única que renderize para ambos.
5. Nenhum gating "inerte até configurar": os hooks copiados assumem o ambiente learnhouse (dev-doctor checa portas fixas), diferente do padrão understand-anything de hook condicionado a config local.
6. Sem distribuição: não é plugin, não é marketplace, não é template git tagueado — só clone manual. (O `wiki-tooling.conf` do guto-wiki público — capítulo 14 — é o único embrião de config central existente nos 3 repos.)

## 9. Fontes

- Local: `/home/augusto/code/harness-wiki/{README.md,manifest.json,SENSITIVE.md,chapters/14-repos-publicos.md,sources/.claude/,sources/.codex/}`; `/home/augusto/.claude/plugins/cache/understand-anything/understand-anything/2.8.1/{hooks/hooks.json,hooks/auto-update-prompt.md,skills/understand/SKILL.md,.claude-plugin/plugin.json}`; `/home/augusto/.claude/plugins/marketplaces/understand-anything/.claude-plugin/marketplace.json`; `/home/augusto/.claude/plugins/installed_plugins.json`.
- Web: copier.readthedocs.io (updating, configuring); github.com/github/spec-kit (README, docs/upgrade.md, discussions #331/#879, issue #1436); chezmoi.io FAQ (usage/design); cruft.github.io + relatos de abandono; agentskills.io / agentman.ai ecosystem report 2026; github.com/obra/superpowers-marketplace.
