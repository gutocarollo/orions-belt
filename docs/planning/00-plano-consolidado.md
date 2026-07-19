# PLANO — Framework de Harness de Agentes Portátil e Auto-Configurável

> Consolida as 8 investigações (`reports/01..08`). Estado: PROPOSTA para revisão adversarial (Planning Adversarial Loop). NÃO executar. Autor: agente principal (Fable/Opus). Data: 2026-07-17.

## 0. Objetivo verdadeiro (reenquadre da dor)

**Dor declarada:** "harness-wiki parametrizável via `.conf`; todas as docs/scripts referenciam variáveis centralizadas; repo incorporável a qualquer projeto que se auto-configure como o understand-anything; integra Claude E Codex; unifica os 3 repos (harness-wiki + guto-wiki + agent-swarm)."

**Objetivo verdadeiro (inferido):** transformar o conhecimento operacional hoje preso ao learnhouse num **produto reutilizável** — um framework que instala, em qualquer projeto de software, o harness de agentes (hooks determinísticos + skills + council adversarial + wiki Karpathy + loop de auto-melhoria), adaptado ao projeto-alvo, mantido por um único ponto de verdade e atualizável sem re-trabalho manual.

**Reenquadre "cavalos mais rápidos" (§7 — 3 divergências da forma pedida, todas com dado):**

1. **`.conf` não basta como mecanismo de instalação.** Pedir "parametrizar via `.conf`" resolve a *leitura* de valores, não a *instalação*, o *update* nem a *adaptação semântica*. O padrão-ouro para "instalar um kit versionado em qualquer projeto, com config central e update preservando customização" é o **Copier** (answers-file gravado no projeto-alvo + `copier update` com merge 3-vias) — a única ferramenta madura da categoria com update que preserva edições locais (cookiecutter não tem; cruft está abandonado; spec-kit faz re-stomp). Fonte: `06-scaffolding-oss.md §1-3`. **O `.conf` continua existindo** — como a materialização legível-por-script do answers-file (padrão que o próprio guto-wiki já iniciou em `wiki-tooling.conf`), sourced pelos hooks/lints. Ou seja: você tem os dois, com papéis distintos.

2. **A premissa "Codex não tem enforcement" caiu.** O agent-swarm construiu uma camada Python (witness/ledger/validate) *porque o Codex não tinha hooks*. **O Codex 0.144 tem hooks nativos estáveis, com o MESMO protocolo do Claude** (`hookSpecificOutput`, `exit 2 = block`, eventos SessionStart/PreToolUse/PostToolUse/Stop/SubagentStart/PreCompact/UserPromptSubmit). Fonte: `05-codex-surface.md §2.5`. Consequência: **o mesmo script de hook e a mesma SKILL.md servem os dois runtimes** — o framework não precisa de duas trilhas paralelas (que já provaram divergir em 4 meses); precisa de UMA fonte + geradores por superfície.

3. **Os 15 capítulos do tutorial NÃO devem ser parametrizados.** Eles contam a *história real* do learnhouse (commits, datas, o incidente dos 18 chromium, a regra dos 17 subagents) — é a evidência que dá credibilidade. Trocar "learnhouse" por `{{PROJECT_NAME}}` no corpo narrativo destruiria isso. Fonte: `03-hardcodes.md §0.1, §4-C`. O framework separa **"estudo de caso de referência" (harness-wiki como está, imutável)** de **"kit instalável" (templates + engine parametrizados)**. São coisas diferentes no mesmo produto.

## 1. Arquitetura-alvo (visão)

Um único repositório-framework com **quatro camadas físicas** (separação engine/config/conteúdo por diretório — o padrão comprovado do understand-anything e hookify, `07-autoconfig-patterns.md §Síntese-1`):

```
agent-harness/                         # nome provisório — ver D1
├── engine/                            # MOTOR runtime-agnóstico (versionado 1×, roda em qualquer projeto)
│   ├── hooks/                         # scripts shell/py neutros: leem JSON do evento + config central
│   ├── lint/                          # docs-wiki-lint.py, ref-integrity.py (versão FORTE do guto-wiki) + _tooling_conf.py (DRY)
│   ├── contract/                      # camada executável do agent-swarm: schemas/*.json, verify_witness.py, agent_swarm_ledger.py, validate_contract.py, render_prompt.py, tests/
│   └── _config.py|.sh                 # loader único do .conf (KEY=value, stdlib, fallback multi-nome)
├── templates/                         # árvore COPIER (destino B — parametrizada por {{VAR}})
│   ├── copier.yml                     # o questionário = a config central na ORIGEM
│   ├── .harness/harness.conf.jinja    # config central materializada no projeto-alvo
│   ├── claude/                        # settings.json.hooks, .claude/skills, .claude/agents/*.md, CLAUDE.md
│   ├── codex/                         # AGENTS.md, .codex/config.toml, .codex/agents/*.toml, hooks.json
│   └── shared/                        # .agents/skills/*/SKILL.md (dual-runtime), loop.md, lessons.md seed, docs/SCHEMA.md
├── skills/                            # skills DO FRAMEWORK (harness-init, harness-doctor) — instaladas no projeto ou como plugin
│   └── harness-init/SKILL.md          # o configurador semântico LLM (understand-anything blueprint)
├── case-study/                        # harness-wiki ATUAL, intocado exceto cap 13/07 (destino C — a narrativa learnhouse)
│   ├── chapters/ llms.txt manifest.json README.md SCHEMA.md
│   └── sources/                       # (sanitizado — sem segredos, ver §7)
├── .claude-plugin/plugin.json         # distribuição como plugin Claude (hooks/skills sem tocar settings.json)
├── llms.txt / README.md / SCHEMA.md   # índice de roteamento do PRÓPRIO framework (Karpathy)
└── VERSION / CHANGELOG.md             # versionamento do template (tags PEP440 p/ copier update)
```

**Distribuição HÍBRIDA em 3 mecanismos, cada um no seu ponto forte** (`06 §7`, `04 §9`, `05 §5`):

- **Copier** = motor de arquivos + update. `uvx copier copy gh:<owner>/agent-harness . --trust` grava `.harness/answers.yml` (config central no projeto) e a árvore de templates renderizada. `copier update` traz versões novas preservando customização (merge 3-vias). Jinja em paths gera `.codex/` só se `use_codex=true`, omite guardas `prod-*` se `client_guards=false`.
- **Registro de hooks — MVP repo-native via Copier (default); plugin é evolução pós-MVP.** REGRA DURA (anti-double-fire, `04 §2.2`: settings-hooks + plugin-hooks **MERGE, ambos rodam** ⇒ completion-gate/ui-evidence-gate disparariam 2×): **por runtime, exatamente UMA fonte de registro de hook — nunca plugin E settings.json juntos.** No MVP o Copier renderiza `settings.json.hooks` (Claude) e `.codex/hooks.json` (Codex) dos mesmos scripts neutros do `engine/` (`06 §7 Camada 2`: "começar repo-native; plugin é decisão adiável"). Empacotar como **plugin Claude** (`hooks/hooks.json` auto-descoberto, `04 §1.2`) é F6/pós-MVP e, se adotado, **substitui** (não soma) o registro em settings.json. No MVP não usamos plugin para o Codex — o Codex até suporta hooks de plugin (`05 §2.5/§2.6`: lê `.claude-plugin/plugin.json`), mas repo-native (`.codex/hooks.json` + trust por hash) é o default; a regra de exclusividade mútua cobre também um eventual plugin-Codex futuro.
- **Skill `harness-init`** = configurador semântico LLM (o "understand-anything" da UX). Roda pós-copy: escaneia o projeto (stack, portas, package manager, serviços, superfícies de memória existentes — matriz de `08-memory-surfaces.md`), preenche o answers-file (`copier --data`), faz MERGE aditivo de `CLAUDE.md`/`AGENTS.md`/`settings.json` preexistentes (nunca overwrite — lição do `mv` que sobrescreveu canônico), e adapta conteúdo por-projeto (banlist, guardas de prod, temas). **Regra dura herdada do blueprint (`07 §Síntese-6`): LLM só AUTORA config; motor determinístico AVALIA; ação bloqueante exige confirmação humana.**

## 2. Config central (destino A) — nomes explicativos

Fonte única: `03-hardcodes.md §3`. ~40 variáveis (das quais ~25 lidas por script em runtime), materializadas em `.harness/harness.conf` (KEY=value, sourced por scripts) e perguntadas via `copier.yml`. Blocos: identidade (`PROJECT_NAME`, `OWNER_NAME`, `GIT_REMOTE_URL`), dev-stack (`HARNESS_DEV_API_PORT=1338`...), prod-opcional (`PROD_STACK_PREFIX`, ausente ⇒ sem guardas de prod), caps do harness (`HARNESS_SUBAGENT_MAX_CONCURRENT=6`, `HARNESS_LESSONS_INJECT_MAX_LINES=80`, `HARNESS_UI_EVIDENCE_SKIP_TTL_SECONDS=14400`, `HARNESS_PLAN_REVIEW_MAX=2`, `HARNESS_EXECUTION_REVIEW_MAX=3`, `HARNESS_ADVERSARIAL_REVIEWER_MODEL`...), convenções (`HARNESS_DOCS_DIR=docs`, `HARNESS_LESSONS_FILE=tasks/lessons.md`). Cada valor hoje tem POUCOS pontos de definição (portas 1× em `dev-doctor.sh:19`; cap 1× em `subagent-throttle.sh:11`) — a migração é barata.

**Particionamento A/B/C/R** (o coração da parametrização, `03 §4`):
- **A** (config central lida por script em runtime): dev-doctor, hooks, verify — externalizar valores hoje hardcoded.
- **B** (placeholder `{{VAR}}` em template Copier): as 12 hookify, ~13 skills, 4+4 agents, settings.json, config.toml, loop.md, banlist, CLAUDE.md/AGENTS.md, e os **seeds da wiki Karpathy: `SCHEMA.md`, `log.md`, `lessons.md`** (o usuário nomeou os 3 explicitamente — todos templatizados com cabeçalho-contrato). **O NOME do arquivo também é template** (`deploy-{{PROD_STACK_PREFIX}}`, `{{PROJECT_NAME}}-delivery-council`) — o bootstrap renomeia, não só substitui conteúdo.
- **C** (narrativa histórica — NÃO templatizar): corpo dos 15 capítulos, `sources/docs/**`, RUN.md, lessons.md **do learnhouse** (o do case-study; o SEED vazio de lessons.md é B). Trade-off vs. o pedido literal ("todas as docs referenciando variáveis"): a narrativa fica intocada de propósito — templatizá-la destruiria a evidência (commits/datas reais) que dá credibilidade; divergência comunicada, reprodutível e reversível (§13.4).
- **R** (redigir — segredo): `apps/api/.env` **já purgado** do harness-wiki nesta sessão (commit `fa390cb`); rotação recomendada antes de publicar.

## 3. O que ABSORVER de cada repo (unificação real)

**De guto-wiki** (`01`): (a) o padrão `.conf` + `load_config()`/`config_csv()` — **extrair para módulo único** `_tooling_conf.py` (hoje triplicado byte-a-byte, DRY que o próprio guto-wiki não fez); (b) a versão FORTE do `docs-wiki-lint.py` (312 vs 165 linhas: flags `--worktree/--staged/--diff-base` + `check_log_format`, `check_frontmatter_updated`, `check_stray_tool_tags`, `check_diff_policy`) — o local é estritamente mais fraco; (c) `.pre-commit-config.yaml` + CI `wiki-integrity.yml`.

**De agent-swarm codex/** (`02`): a **pilha de enforcement em 4 camadas** (schemas JSON dos reviews → witness de marcadores load-bearing → 16 testes de contrato com teste NEGATIVO → `validate_contract.py` entrada única) + **ledger JSONL** por rodada de loop + **render_prompt.py**. Tudo stdlib, portável. **Religar aos hooks nativos** (novidade do Codex+Claude): witness/sentinel-check como Stop hook, ledger como PostToolUse/SubagentStop hook — em vez de "validação local por disciplina".

**Merge das 2 linhagens do council** (`02 §c` — pré-requisito, não melhoria): a versão única funde `REPLAN-REQUEST/CONSUMED` + `FIX-REQUEST/CONSUMED` + gates de rodada final + ledger (codex) COM review-sempre-em-subagent + `REVISORES:` + continuação do mesmo subagent + guards Understand-Anything (learnhouse vivo). Nenhuma das duas sozinha é o estado da arte. Protegido depois por witness + testes.

## 4. Multi-agente: 1 fonte → geradores por superfície (`05 §5`)

Matriz de paridade (do `05 §3`): instruções (CLAUDE.md ↔ cadeia AGENTS.md, com `project_doc_fallback_filenames` mapeando CLAUDE.md); hooks (settings.json.hooks ↔ .codex/hooks.json — MESMO protocolo); skills (`.agents/skills` servem os dois; symlink/cópia p/ `.claude/skills` no bootstrap); agents (`.claude/agents/*.md` ↔ `.codex/agents/*.toml` — gerar os dois do manifesto); MCP (`.mcp.json` ↔ `[mcp_servers]` no config.toml). **Escrever hook uma vez** (script neutro lendo o JSON comum), registrar nos dois. **Automatizar o espelho AGENTS.md←CLAUDE.md** (hoje sync manual com drift "última sync 2026-07-06" — `08 §c`), com filtro de bloco sensível (infra/prod fora do AGENTS.md).

Limites duros restantes (`05 §4`): argumentos formais de skill (bloco `ARGS:` textual permanece); `SessionEnd`/`Notification` inexistem no Codex; bootstrap Codex precisa de 3 passos extras (trust do projeto, trust dos hooks por hash, smoke-test de `spawn_agent` — regressão #14579); dimensionar `project_doc_max_bytes` (default 32KiB trunca).

## 5. Auto-configuração (o "understand-anything" da UX) — `07`

Blueprint portado 1:1: (a) **cascata de resolução de root multi-agente** (`$CLAUDE_PLUGIN_ROOT` → `$HOME/.codex/...` → `$HOME/.opencode/...` → fallback) — a peça que falta hoje; (b) **fronteira determinístico/LLM** (enumeração, detecção de stack por extensão/filename, portas por scan de compose/env, fingerprint = SEMPRE script; síntese de narrativa/regra = SEMPRE LLM); (c) **zero-token gate** (não re-rodar LLM sem mudança real); (d) **`meta.json{gitCommitHash}`** como âncora de staleness (mais robusto que hash decorado no CLAUDE.md — que já driftou, achado do cap 13); (e) **fail-open em toda borda de config** (config ausente/malformada ⇒ modo default, nunca crash); (f) LLM gera config sob **confirmação humana** quando a ação é bloqueante (padrão `/hookify:hookify`).

Detecção de superfícies (matriz de 19 de `08`), com comportamento explícito por escopo:
- **LOCAL do projeto (read-write, MERGE aditivo):** `CLAUDE.md`/`AGENTS.md`/`settings.json` preexistentes → merge, nunca overwrite; gera o bloco de allowlist do `.gitignore` para `.claude/`.
- **GLOBAL Claude/Codex (read-only, DETECTA e REPORTA, nunca popula):** `~/.claude/CLAUDE.md`, `~/.claude/rules/*.md`, `~/.claude/projects/<slug>/memory/MEMORY.md` + topic files (slug computado da **raiz do repo-alvo**, não do CWD — armadilha `08 achado 3`: rodar de `apps/web/` gera slug diferente), `~/.codex/AGENTS.md`, `~/.codex/config.toml`, `~/.codex/memories_1.sqlite`. Objetivo: evitar duplicar regra já coberta globalmente (ex.: Context7) e avisar de drift. **NUNCA copia `~/.claude/settings.json` chave `env`** (contém `GH_TOKEN`/`GITHUB_TOKEN` em claro — `08 achado 4`).
- **Passo 0:** exigir repositório git (`central-ordens-bi` nem é repo — `08 achado 5`); recusar ou `git init` sob confirmação.
- **Argumento de runtime:** `harness-init --agent claude|codex|both` (default `both`) — controla quais superfícies gerar (padrão spec-kit `--ai`, `06 §3`).

## 6. Fases (WBS sequencial — LEI ZERO §6, 1 por vez, testada)

- **F0 — Fundação da config.** Criar `_tooling_conf` (DRY do guto-wiki) + `.harness/harness.conf` schema + fazer `dev-doctor.sh`/hooks/`verify.py` lerem dele (destino A). Teste: hooks funcionam idênticos lendo do .conf. *Gate: sem regressão nos hooks atuais do learnhouse.*
- **F1 — Absorver o lint forte + contrato executável.** Portar docs-wiki-lint 312-linhas + schemas/witness/ledger/validate do agent-swarm para `engine/`, parametrizados (paths e listas do .conf). Teste: `validate_contract.py` verde (16/16) no novo layout.
- **F1.5 — Merge do council** (as 2 linhagens, pré-condição de F3) → SKILL.md única dual-runtime, protegida por witness + testes novos. *Gate: witness verde nos marcadores dos 2 handoffs + subagent-obrigatório; teste NEGATIVO passa; council único citado idêntico em Claude e Codex.*
- **F1.6 — Des-driftar o AGENTS.md (pré-condição de F3).** ANTES de extrair template do learnhouse: regenerar `AGENTS.md` do `.claude/CLAUDE.md` atual (hoje driftado, "sync 2026-07-06", faltam §15/§16 — `05 §53`) por filtro determinístico. **Alvo condicionado a D11:** se D11=consumidor, opera IN-PLACE no learnhouse vivo (e a lista de exceção da F3 fica vazia — diff-zero em tudo); se D11=fonte-imutável, opera numa CÓPIA de extração (e a lista de exceção da F3 enumera council+AGENTS.md). *Gate: AGENTS.md derivado do CLAUDE.md por filtro determinístico, sem bloco de infra/prod.*
- **F3 — Templatização (B).** Converter as 12 hookify + skills + agents + settings + configs em templates Copier com `{{VAR}}`; `copier.yml` = a config central. *Migração 1-por-1, arquivo a arquivo.* **Gate (corrigido):** renderizar o learnhouse do template e provar **diff-zero para todo arquivo B EXCETO a lista nominal de arquivos que DEVEM diferir** (o council pós-F2 e o AGENTS.md des-driftado da F1.5) — enumerar essa lista explicitamente; qualquer diff fora dela é regressão.
- **F4 — Geradores multi-agente.** Do manifesto único emitir Claude (settings.json.hooks + .claude/agents/*.md) e Codex (.codex/hooks.json + .codex/agents/*.toml + AGENTS.md filtrado). *Gate: artefato gerado == mão-escrito byte-a-byte para o learnhouse; smoke-test `spawn_agent` enxerga agents do repo (regressão Codex #14579).*
- **F5 — Configurador `harness-init`.** Skill LLM: scan → answers → merge aditivo → adaptação semântica confirmada; detecção global read-only (§5). Blueprint understand-anything. **RELATÓRIO DE APLICABILIDADE POR STACK (decisão D5):** o framework instala TUDO, mas o `harness-init` primeiro **detecta a stack** (linguagem, framework web, gerenciador de pacote, orquestrador, presença de Next.js/Docker Swarm/Playwright/Postgres) e **apresenta, via skill, um relatório por componente: APLICÁVEL / NÃO-APLICÁVEL / CONDICIONAL** — ex.: `ui-evidence-gate` (Playwright+Next) marcado NÃO-APLICÁVEL num repo Python puro; `deploy-*` marcado CONDICIONAL se não houver Swarm/EasyPanel; `understand-apps-diff-guard` CONDICIONAL a `PROJECT_ROOT≠git-root`. **O usuário decide por componente** (ativar/pular); a decisão grava em `.harness/answers.yml` (flags por módulo). Nada é ativado silenciosamente contra a stack. *Gate: rodar num repo git limpo produz `.harness/answers.yml` válido + o relatório de aplicabilidade classifica corretamente os hooks stack-específicos numa fixture Python-pura e numa Next.js; merge NÃO-destrutivo de um CLAUDE.md preexistente; `--agent claude|codex|both` gera só as superfícies pedidas.*
- **F6 — Plugin + distribuição (pós-MVP, gated por D2).** `.claude-plugin/plugin.json` + marketplace; passos de trust Codex; `harness-doctor` (selftest). Ao ativar plugin, REMOVER o registro settings.json (regra anti-double-fire §1). *Gate: `claude --plugin-dir ./…` carrega; `harness-doctor` verde; grep confirma que hooks não estão em settings.json E plugin ao mesmo tempo.*
- **F7 — Case-study + wiki do framework.** Mover harness-wiki para `case-study/` (intocado, **exceto** cap 13/07 atualizados com o mecanismo GENÉRICO do plugin — gap de `07 §Gaps`); llms.txt/README/SCHEMA do próprio framework. *Gate: `verify.py` do case-study verde; lint Karpathy do framework verde.*
- **F8 — Prova end-to-end.** Instalar em 2 projetos-alvo de perfis opostos (`learnhouse-upstream-1.3.1` limpo + um repo sem harness) e validar auto-config + `copier update`. *Gate: os 2 sobem com hooks disparando 1× (não 2×), harness-init idempotente, update preserva customização (merge 3-vias sem perder edição local).*

## 7. Segurança e sanitização (bloqueante antes de publicar)

Checklist herdado da trilha claude do agent-swarm (`02 §rec8`) + achados desta sessão: (a) **rotacionar** as chaves que estiveram em `apps/api/.env` (JWT/AWS-R2/Gemini/OpenRouter/xAI) — expostas em disco fora do repo original; (b) IPs (`187.127.10.14`, `100.98.49.77`) → redigir; (c) nunca versionar `**/.env*` nem copiar a chave `env` do `~/.claude/settings.json` (tem `GH_TOKEN` em claro); (d) `SENSITIVE.md` vira SAÍDA de um scanner (seed = padrões da tabela `03 §2`), não relatório manual; (e) o framework nasce com o checklist de publicação embutido (guarda `AGENTS.md:24-25` do agent-swarm: "não copie CLAUDE.md privado/credenciais/dumps").

## 8. Não-objetivos (MVP)

Agents SDK / OpenAI API-key como base (decisão D1 do PLANO-SWARM: runtime nativo; SDK só camada externa futura); memória SQLite nativa do Codex (`memories` experimental/off — lessons.md continua a fonte); suporte a Cursor/Gemini/Copilot (detectar e reportar, não gerar — o par é Claude+Codex); loop `/loop` nativo no Codex (vira `codex exec` via cron).

## 9. Riscos

R0 — **double-fire de hooks** se plugin e settings.json coexistirem (`04 §2.2`): mitigado pela regra de exclusividade mútua por runtime (§1) + gate grep na F6. R1 — `copier update` exige disciplina de tags e working-tree limpa; merge 3-vias pode conflitar (mitiga: `_skip_if_exists` p/ living files, migrations versionadas). R2 — mapeamento de campo por-tool do hookify é hardcoded por tool conhecida (`07 §B.3`); tools do Codex com schema diferente exigem adaptação. R3 — trust de hooks por hash no Codex quebra a cada edição do hook (documentar). R4 — F2/F3 tocam o learnhouse vivo se ele for consumidor (D11). R5 — dois formatos de config (answers.yml Copier + harness.conf sourced) podem driftar (mitiga: harness.conf é GERADO do answers, nunca editado à mão).

## 10. Decisões abertas (D[n]) — para clarification-plan

**Decisões humanas reais (bloqueantes — vão para a clarificação):**
D1 topologia/nome do repo unificado (novo `agent-harness` vs dentro de guto-wiki/agent-swarm) · D2 mecanismo primário de distribuição no MVP (Copier repo-native vs plugin já no v1) · D5 escopo do MVP v1 (quais peças do harness entram) · D6 público vs privado primeiro (urgência de sanitização/rotação) · D9 grau de autonomia do configurador (auto vs propor-e-confirmar) · D10 convenção de naming/prefixo dos componentes · **D11 (novo, de G5): o learnhouse VIVO vira CONSUMIDOR do framework (seu `.claude/` passa a ser gerado) ou permanece a FONTE-doadora imutável?** — decide se F2/F3 editam produção de trabalho.

**Rebaixadas a CONFIRMAR (o dado já aponta a resposta; não são escolha aberta):**
D3 destino do tutorial → case-study imutável (exceto cap 13/07) — `03 §0.1`, §13.4. D4 formato do config → answers.yml (Copier) + harness.conf (KEY=value sourced) — os dois, `01 §Obs-2`. D7 merge do council → sim, é pré-requisito (F1.5/F2) — `02 rec1`; o que resta de D7 é coberto por D11. D8 absorver contrato executável (schemas/witness/ledger) → sim, é a espinha — `02 rec2`; o "quanto" é absorvido por D5 (escopo MVP).

(Detalhe com trade-offs aplicados na fase de clarificação — máx. 10 blocos D[n].)

## 11. Decisões RESOLVIDAS (2026-07-17 — não executar ainda)

| D | Decisão | Escolha | Efeito no plano |
|---|---|---|---|
| D1 | Topologia/nome | **Novo repo `agent-harness`, SEM deprecar** guto-wiki/agent-swarm (ficam como estão por ora) | Cria 4º repo; §1 vale; sem commits de superseded nos antigos agora |
| D2 | Distribuição MVP | **Copier repo-native** (default recomendado; plugin = F6/pós-MVP) | §1 regra anti-double-fire; F6 gated |
| D3 | Tutorial | **Case-study imutável** (exceto cap 13/07) | confirmado por dado |
| D4 | Config central | **answers.yml (Copier) + harness.conf (KEY=value sourced)** | confirmado por dado |
| D5 | Escopo MVP | **TUDO instalável, mas `harness-init` verifica a STACK e propõe via skill o que é APLICÁVEL/NÃO/CONDICIONAL; usuário decide por componente** | F5 ganha o relatório de aplicabilidade por stack; nada ativado contra a stack |
| D6 | Público/privado | **Privado primeiro**; publicar só após sanitizar case-study + ROTACIONAR chaves do .env | §7 é gate de publicação |
| D7 | Merge council | **Sim** (pré-requisito F1.5) | confirmado por dado |
| D8 | Contrato executável | **Sim** (espinha; schemas/witness/ledger) | confirmado por dado |
| D9 | Autonomia configurador | **Propor-e-confirmar** (default; reforçado pela própria D5) | F5 |
| D10 | Naming | **Prefixo por `PROJECT_NAME`** (default) | F3/F4 renomeiam arquivos |
| D11 | Papel do learnhouse | **Fonte-doadora IMUTÁVEL** — não editar o `.claude/` vivo | F1.5/F1.6 operam em CÓPIA de extração; lista de exceção da F3 enumera council+AGENTS.md; F2/F3 NÃO tocam produção |

**Consequência de D11=imutável para as fases:** F1.5 (merge council) e F1.6 (des-drift AGENTS.md) rodam sobre uma cópia extraída do learnhouse, não in-place. O learnhouse vivo permanece intacto durante toda a construção do framework. Migrar o learnhouse a consumidor é decisão futura separada (pós-F8).

**Status:** PLANO FINALIZADO e revisado (Planning Adversarial Loop 2/2 SATISFEITO). Execução NÃO iniciada por instrução do dono. Caminho de execução definido pelo dono: subagent **sonnet** executa; **1** loop de verificação adversarial com **fable** ao final.
