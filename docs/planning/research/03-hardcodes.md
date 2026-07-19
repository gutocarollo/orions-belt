# INVESTIGAÇÃO 3 — Auditoria de valores hardcoded que bloqueiam portabilidade (harness-wiki)

Data: 2026-07-17. Alvo: `/home/augusto/code/harness-wiki` (chapters/, sources/, README.md, SCHEMA.md, SENSITIVE.md, llms.txt, manifest.json, verify.py, log.md). Método: grep sistemático por categoria + leitura dos arquivos decisivos. Todas as contagens são de ocorrências de string (grep -o), formato `capítulos+meta / sources`.

## 0. Veredicto executivo

1. **A sensibilidade e o acoplamento NÃO estão nos capítulos — estão em `sources/`.** Os capítulos citam valores do learnhouse como NARRATIVA (história real auditada, com commits e datas); `sources/` contém os arquivos executáveis reais com portas, serviços, credenciais. A estratégia correta é: capítulos = destino **C** (exemplo histórico intocado), `sources/` executáveis = destino **A/B** (config + template), docs espelhados = **C**.
2. **ACHADO CRÍTICO (bloqueia qualquer publicação/port):** `sources/apps/api/.env` contém **segredos VIVOS**, não "credenciais de teste": JWT secret (Linha 6), `COLLAB_INTERNAL_KEY` (Linha 7), `LEARNHOUSE_GEMINI_API_KEY` (Linha 22), chaves R2/AWS ativas + reservas comentadas (Linhas 35-39), `OPENROUTER_API_KEY` (Linha 41), `XAI_API_KEY` (Linha 44), `LEARNHOUSE_CONTENT_SIGNED_URL_SECRET` (Linha 48). O `SENSITIVE.md` (Linha 57) subdescreve isso como "Credenciais de teste do e2e". Destino: **R (redigir/remover)** — nem variável, nem template.
3. O volume de acoplamento é grande mas CONCENTRADO: `learnhouse` 115/285 ocorrências, `qq-academy` 69/127, portas dev (1338/3009/5433) ~65/114, `.claude/` 536 menções nos capítulos. A boa notícia: os valores executáveis têm POUCOS pontos de definição (ex.: portas definidas 1× em `dev-doctor.sh:19`; cap de subagents 1× em `subagent-throttle.sh:11`).

## 1. Metodologia e universo

- 22 arquivos de conteúdo/meta na raiz + 15 capítulos + 107 arquivos em `sources/` (excluindo `.git/`, `.mypy_cache/`).
- Greps por 10 categorias do escopo. Contagem `A/B` = (chapters+README+SCHEMA+SENSITIVE+llms.txt+manifest.json+verify.py+log.md) / (sources/).

## 2. TABELA-MESTRA — path → linha(s) → valor → categoria → variável proposta → destino

Legenda de destino: **A** = variável de config central do framework; **B** = placeholder `{{VAR}}` em template regenerável; **C** = permanece como exemplo/narrativa histórica; **R** = redigir/remover (segredo).

### 2.1 Paths absolutos (`/home/augusto/...`) — 12 ocorrências em chapters, 59 em sources

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `chapters/07-hookify.md` | 11, 47, 91, 120, 229, 317, 326 | `/home/augusto/code/learnhouse/...`, `/home/augusto/.claude/plugins/cache/...` | `{{PROJECT_ROOT}}`, `{{CLAUDE_USER_DIR}}` | C (narrativa) — mas na geração FUTURA de capítulos, usar `{{PROJECT_ROOT}}` |
| `chapters/03-hooks-prompt.md` | 90 | `/home/augusto/code/learnhouse` (saída de `git rev-parse`) | — | C (prova histórica citada de doc) |
| `chapters/13-understand-anything.md` | 24, 26 | idem | — | C |
| `chapters/04-hooks-pretooluse.md` | 40 | idem | — | C |
| `sources/scripts/understand-apps-changed-files.sh`, `sources/.claude/hookify.bare-python.local.md`, `sources/.claude/hookify.relative-cd.local.md`, `sources/.claude/CLAUDE.md`, `sources/.claude/skills/{learnhouse-delivery-council,adversarial-review}/SKILL.md` | várias | `/home/augusto/code/learnhouse/...` | `{{PROJECT_ROOT}}` ou `$CLAUDE_PROJECT_DIR` | B (templates dos artefatos operacionais) |
| `sources/docs/**`, `sources/.claude/runs/done/**` | várias | paths antigos (`/home/augustocarollo/...` em `2026-06-25-auditoria...md:4`) | — | C (docs históricos espelhados) |

**Nota positiva:** os hooks executáveis JÁ são portáveis neste ponto — usam `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}` (ex.: `sources/.claude/hooks/subagent-throttle.sh:8`, `reap-leaks.sh:11`). O anti-padrão está nos hookify `.local.md` e nas skills, que embutem path absoluto em prosa de instrução.

### 2.2 Nome do projeto/repo — `learnhouse` 115/285; `harness-wiki` ~40 no meta

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `llms.txt` | 1 | "harness de automações ... do LearnHouse" | `{{PROJECT_NAME}}`, `{{WIKI_NAME}}` | B (índice regenerável) |
| `README.md` | 58 | "repositório privado **learnhouse** (projeto Quero-Quero Academy)" | `{{PROJECT_NAME}}`, `{{CLIENT_PRODUCT_NAME}}` | B |
| `manifest.json` | 226, 291 (raw count: 4× learnhouse, 2× qq-academy, 3× guto) | "skill learnhouse-delivery-council", "deploy-qq-academy" | `{{COUNCIL_SKILL_NAME}}` = `{{PROJECT_NAME}}-delivery-council` | B |
| `SCHEMA.md` | 48, 50, 54 | "divergência deliberada do learnhouse", origem | `{{SOURCE_REPO_NAME}}` | B |
| `verify.py` | 2, 53, 57 | "harness-wiki verify" | `{{WIKI_NAME}}` | B (ou A: `WIKI_NAME` lida de config) |
| `chapters/*` (todos) | linha 1 de cada | header `> **harness-wiki** · [índice]...` | `{{WIKI_NAME}}` | B (header injetado na geração) |
| `chapters/*` corpo | ~100 ocorrências | "learnhouse", "no learnhouse" | — | C (narrativa) |
| `sources/.claude/skills/*`, `sources/.claude/agents/*.md`, `sources/.codex/agents/*.toml` | nomes de arquivo E frontmatter `name:` | `learnhouse-delivery-council`, `learnhouse-adversarial-reviewer`, `learnhouse-context-scout`, `learnhouse-implementer`, `learnhouse-test-auditor`, `run-learnhouse` | `{{PROJECT_NAME}}-delivery-council` etc. — padrão `{{PROJECT_NAME}}-<papel>` | B (o framework gera com prefixo do projeto) |
| `sources/apps/api/.env` | 9, 10 | `postgresql://learnhouse:learnhouse@localhost:5433/learnhouse` | `{{DEV_DB_USER}}`, `{{DEV_DB_NAME}}`, `HARNESS_DEV_DB_PORT` | B/R (exemplo deve virar placeholder; senha real fora) |
| `sources/scripts/dev-doctor.sh` | 18, 55, 59-63 | `/tmp/learnhouse-dev`, `learnhouse-db-dev` etc. | ver 2.7 | A |

Frequência de nomes de componente prefixados (chapters+meta): `qq-live` 29, `qq-prod` 23, `deploy-qq-academy` 17, `learnhouse-delivery-council` 14, `learnhouse-adversarial-reviewer` 10, `learnhouse-implementer` 8, `learnhouse-test-auditor` 7, `learnhouse-context-scout` 7, `run-learnhouse` 6.

### 2.3 Nome do cliente — `qq-academy` 69/127, `Quero-Quero` 14/40, `queroquero` 5/57

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `SENSITIVE.md` | 5, 55-58 | "Quero-Quero, qq-academy", `qq-prod-*` | — | C (é o catálogo da sensibilidade; no framework vira relatório gerado) |
| `README.md` | 58 | "projeto Quero-Quero Academy" | `{{CLIENT_PRODUCT_NAME}}` | B |
| `manifest.json` | 137, 143, 161, 172, 182, 189 | keywords/resumos `qq-prod`, `qq-live`, `deploy-qq-academy` | `{{PROD_GUARD_PREFIX}}`, `{{DEPLOY_SKILL_NAME}}` | B |
| `chapters/07-hookify.md` | 57-61, 91-207 (13 linhas c/ serviços) | regras `qq-prod-*`, serviços `qq-academy_*` | — | C (narrativa dos 5 guardas reais) |
| `chapters/09-skills-operacionais.md` | 104 e seção deploy | `deploy-qq-academy`, URL de prod | — | C |
| `sources/.claude/hookify.qq-prod-{destroy,image-source,prune,push-latest,update-monitor}.local.md` | pattern/corpo (ex. destroy: pattern na Linha 6, corpo Linhas 9-15) | `qq-academy`, `cloudflare-tunnel`, `easypanel`, `qq-academy_[a-z]+=0` | `{{PROD_STACK_PREFIX}}` (=`qq-academy`), `{{PROD_PROTECTED_SERVICES}}` | B — é O template canônico de "guarda de produção" do framework |
| `sources/.claude/skills/deploy-qq-academy/SKILL.md` | 2, 21-36, 49-93 | serviços, registry, URLs, bind mounts | `{{PROD_STACK_PREFIX}}`, `{{PROD_REGISTRY_URL}}`, `{{PROD_PUBLIC_WEB_URL}}` | B |
| `sources/.claude/deliverable-banlist.txt` | 10-16 (globs), 33 (`\blearnhouse\b`) | globs `docs/commercial/*`, ban do nome interno | `{{DELIVERABLE_GLOBS}}`, `{{INTERNAL_NAMES_BANNED}}` | B — a banlist é por-projeto por definição |
| `sources/apps/web/.env.local` | 9 | `NEXT_PUBLIC_LEARNHOUSE_DEFAULT_ORG=queroquero` | `{{CLIENT_ORG_SLUG}}` | B/R |
| `sources/docs/**` (auditorias, planos, manual-usuario) | dezenas | Quero-Quero em contexto comercial | — | C (ou EXCLUIR do port — ver §5) |

### 2.4 Hosts/URLs/IPs — `easypanel` 7/28, `kj6gzi` 1/13, `srv1777233` 0/5, `cloudflare` 10/100

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/.claude/skills/deploy-qq-academy/SKILL.md` | 21 | VPS `srv1777233`, **IP `187.127.10.14`** | `{{PROD_HOST_NAME}}`, `{{PROD_HOST_IP}}` | B (IP público: considerar R) |
| idem | 27-30, 53, 61-62, 76-93 | `localhost:5000` (registry), `https://qq-academy-web.kj6gzi.easypanel.host`, `https://qq-academy-api.kj6gzi...` | `{{PROD_REGISTRY_URL}}`, `{{PROD_PUBLIC_WEB_URL}}`, `{{PROD_PUBLIC_API_URL}}` | B |
| `sources/apps/api/.env` | 14 | `http://100.98.49.77:3009` (IP Tailscale privado) | — | R |
| `sources/apps/api/.env` | 47 | `https://media.orion-code.tech` | `{{CONTENT_CDN_BASE_URL}}` | B |
| `sources/.claude/CLAUDE.md` | (bloco PRODUÇÃO) | URLs kj6gzi, srv1777233 | `{{PROD_*}}` | B |
| `chapters/09-skills-operacionais.md` | 104 | menção ao state-check c/ serviços | — | C |
| `sources/docs/**`, `sources/.claude/runs/done/**`, `sources/.claude/contracts/*` | várias (`contracts/...seaweedfs...md:24` tem "VPS srv1777233 Hostinger, Campinas-SP") | hosts de prod | — | C ou excluir |

### 2.5 Portas — 1338 (18/40), 3009 (28/46), 5433 (19/28), 5432 (18/19), 18114 (4/4), 18115 (4/5), 6379 (2/10), 3000, 5000, 4000, 3001

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/scripts/dev-doctor.sh` | **19** (`API_PORT=1338 WEB_PORT=3009`), 9-12, 63, 66-67 | 1338, 3009, 5433, 18114, 18115 | `HARNESS_DEV_API_PORT`, `HARNESS_DEV_WEB_PORT`, `HARNESS_DEV_DB_PORT`, `HARNESS_MCP_DB_DEV_PORT`, `HARNESS_MCP_DB_PROD_PORT` | **A** (fonte única real — o script já centraliza em vars locais; promover a config) |
| `sources/.claude/hookify.db-port-5432.local.md` | 15, 17 | 5433 (host) vs 5432 (container) | `HARNESS_DEV_DB_PORT`, `HARNESS_DEV_DB_INTERNAL_PORT` | B (template de guarda) |
| `sources/.claude/hookify.web-dev-port.local.md` | 12, 18, 20 | pattern `3009`; "3000 = EasyPanel" | `HARNESS_DEV_WEB_PORT`, `HARNESS_RESERVED_PORTS` | B |
| `sources/apps/api/.env` | 9, 10, 12-14 | 5433, 6379, 3001, 3000, 3007, 3009 | `HARNESS_DEV_*_PORT` | B/R |
| `sources/apps/web/.env.local` | 3-6 | 1338, 4000 (collab ws), 3009, `PORT=3000` | `HARNESS_DEV_API_PORT`, `HARNESS_DEV_COLLAB_PORT` | B/R |
| `chapters/02-hooks-sessionstart.md` | 11, 21, 23, 35, 43 | portas no retrato do dev-doctor | — | C |
| `chapters/07-hookify.md` | 216-276, 338-361 | portas na narrativa das regras | — | C |
| `chapters/09-skills-operacionais.md` | 212-239 | portas na narrativa do run-learnhouse | — | C |
| `llms.txt` | 10 | "portas 1338/3009/5433" no resumo do cap. 02 | `{{...}}` só se o capítulo for regenerado | B-condicional (índice descreve o capítulo; segue o destino do capítulo) |
| `manifest.json` | 34, 43-45 | keywords "1338", "3009", "5433" | idem | B-condicional |

### 2.6 Credenciais de teste e SEGREDOS — `admin@school.dev` 2/6, `admin12345` 1/5

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/apps/api/.env` | 16-17 | `LEARNHOUSE_INITIAL_ADMIN_EMAIL=admin@school.dev` / `ChangeMe123!` | `{{E2E_ADMIN_EMAIL}}`, `{{E2E_ADMIN_PASSWORD}}` | B |
| `sources/apps/api/.env` | **6, 7, 22, 35-39, 41, 44, 48** | JWT secret, collab key, Gemini key, R2 AWS keys (+2 comentadas), OpenRouter key, xAI key, signed-URL secret | — | **R — remover/redigir JÁ; são segredos vivos, não exemplo** |
| `sources/.claude/skills/ui-evidence/SKILL.md` | 46-47 | `admin@school.dev` / `admin12345` | `{{E2E_ADMIN_EMAIL}}` / `{{E2E_ADMIN_PASSWORD}}` | B |
| `sources/.claude/CLAUDE.md` | 143 (item 3 do bloco prod) | e2e admin | idem | B |
| `sources/docs/planos/2026-07-08-...expo.md:570`, `sources/.claude/runs/done/{mobile-expo:76,netflix-ui:40}/RUN.md` | credencial em docs históricos | — | C |
| `chapters/09-skills-operacionais.md` | 72 | credencial na narrativa | — | C |

### 2.7 Nomes de serviço docker — `learnhouse-*-dev` 7/20, `qq-academy_*` 17/37

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/scripts/dev-doctor.sh` | 55, 59-63 | `learnhouse-db-dev`, `learnhouse-redis-dev`, `learnhouse-gotenberg-dev`, `learnhouse-worker-dev` | `HARNESS_DEV_CONTAINER_PREFIX` (=`{{PROJECT_NAME}}-`) + sufixos `-db-dev` etc.; ou lista `HARNESS_DEV_CONTAINERS` | **A** |
| `sources/scripts/dev-doctor.sh` | 13, 64-65 | `mcp-postgres-learnhouse-dev/prod`, imagem `local/postgres-mcp-proxy:python3.14` | `HARNESS_MCP_DB_CONTAINER_{DEV,PROD}`, `HARNESS_MCP_PROXY_IMAGE` | A |
| `sources/.claude/hookify.qq-prod-*.local.md` | patterns | `qq-academy_[a-z]+`, `cloudflare-tunnel`, `easypanel` | `{{PROD_STACK_PREFIX}}`, `{{PROD_PROTECTED_SERVICES}}` | B |
| `sources/.claude/skills/deploy-qq-academy/SKILL.md` | 24, 49-93 | `qq-academy_{api,web,collab,postgres,redis}` | `{{PROD_STACK_PREFIX}}_{{service}}` | B |
| `chapters/02:16-17,43`, `chapters/07` (13 linhas), `chapters/01:106`, `chapters/09:104` | narrativa | — | — | C |

### 2.8 Nomes de modelo — `fable` 4/23 (opus/sonnet: 0)

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/.claude/runs/done/mobile-expo/RUN.md` | 56, 108 | "learnhouse-adversarial-reviewer `model: fable`" (regra do Augusto 2026-07-08) | `HARNESS_ADVERSARIAL_REVIEWER_MODEL` | C (RUN histórico) — mas a REGRA deve virar variável A no framework |
| `sources/.claude/runs/done/{netflix-ui:20,41; netflix-r5:17,32,52-53; netflix-ui-mobile-polish:7,15,20; netflix-audit-fix:18}` | vários | reviews com fable | — | C |
| `sources/tasks/lessons.md` | 87, 129 | fable em lições | — | C |
| `sources/docs/planos/2026-07-10-...:81` | fable | — | C |
| `chapters/11-council-subagents.md` | 11, 163 | narrativa | — | C |
| `sources/.claude/agents/*.md` frontmatter | (sem campo `model:` hoje — a regra vive só em RUN.md/memória) | — | `HARNESS_ADVERSARIAL_REVIEWER_MODEL` | **A — gap: o framework deve materializar `model:` no agent template** |

### 2.9 Caps numéricos

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/.claude/hooks/subagent-throttle.sh` | **11** (`CAP=6`), 14 (`-mmin +45`) | 6 subagents; slot stale 45min | `HARNESS_SUBAGENT_MAX_CONCURRENT`, `HARNESS_SUBAGENT_SLOT_STALE_MINUTES` | **A** |
| `sources/.claude/hooks/lessons-inject.sh` | **8** (`MAX_LINES=80`), 11 | janela de injeção | `HARNESS_LESSONS_INJECT_MAX_LINES` | **A** |
| `sources/.claude/hooks/ui-evidence-gate.sh` | **38** (`14400`) | TTL 4h do escape SKIP | `HARNESS_UI_EVIDENCE_SKIP_TTL_SECONDS` | **A** |
| `sources/scripts/dev-doctor.sh` | 112, 116 (`-gt 300`); 70-71, 122-123 (`>50% CPU`, `>3600s`) | chromium órfão >300s; runaway 50%/1h | `HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS`, `HARNESS_RUNAWAY_CPU_PCT`, `HARNESS_RUNAWAY_MIN_AGE_SECONDS` | **A** |
| `sources/.claude/hooks/marathon-stop-gate.sh` | 4, 28-31 | anti-prisão: 3 strikes | `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS` | **A** |
| `sources/.codex/config.toml` | 1, 4, 5 | `project_doc_max_bytes=65536`, `max_threads=4`, `max_depth=1` | `HARNESS_CODEX_PROJECT_DOC_MAX_BYTES`, `HARNESS_CODEX_MAX_THREADS`, `HARNESS_CODEX_MAX_DEPTH` | **A** (gerado no arquivo pelo bootstrap) |
| `sources/.claude/skills/learnhouse-delivery-council/SKILL.md` | 35-36 | `PLAN_REVIEW_MAX=2`, `EXECUTION_REVIEW_MAX=3` | `HARNESS_PLAN_REVIEW_MAX`, `HARNESS_EXECUTION_REVIEW_MAX` | B (defaults do template; overridable por ARGS) |
| `sources/.claude/settings.json` | timeouts 10/15 por hook | timeouts | `HARNESS_HOOK_TIMEOUT_SECONDS` (default 10) | A/B |
| `chapters/04:55-56,64`, `chapters/01:197`, `chapters/06:51,166`, `chapters/02:89`, `chapters/12:61`, `chapters/15:17`, `chapters/11:117,141,228,235` | narrativa dos caps (6, 45min, 80, 14400, 300s, 2/3 rodadas) | — | — | C |

### 2.10 Emails/nomes de pessoa — `Augusto` 64/92, `gutocarollo` 8/11

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/.claude/hooks/subagent-throttle.sh` | 3-4, 18 | "Regra do Augusto (2026-06-22): ... lance 6 no maximo" | `{{OWNER_NAME}}` (comentário) | B (template) / manter citação como origem |
| `sources/.claude/hooks/git-doctor.sh` | 42 | `git@github.com:gutocarollo/...` | `{{GIT_REMOTE_OWNER}}` | B |
| `sources/.claude/skills/git-delivery/SKILL.md` | 20, 33 | `git@github.com:gutocarollo/queroquero-academy.git`; "Hi gutocarollo!" | `{{GIT_REMOTE_URL}}`, `{{GIT_REMOTE_OWNER}}` | B |
| `chapters/14-repos-publicos.md` | 44, 64, 77 | `github.com/gutocarollo/{guto-wiki,agent-swarm}` | `{{PUBLIC_WIKI_REPO_URL}}`, `{{PUBLIC_SWARM_REPO_URL}}` | C hoje; A no framework (são os repos a unificar) |
| `chapters/*` (59 linhas) | "Augusto" na narrativa (13 arquivos; pico: cap.09 com 13, caps.03/07 com 9) | — | `{{OWNER_NAME}}` | C |
| `chapters/09-skills-operacionais.md` | 140-165 | escada de credencial c/ gutocarollo | — | C |
| `sources/docs/auditorias/2026-06-25-...md` | 4 | `/home/augustocarol...` (máquina ANTIGA — WSL) | — | C |

### 2.11 Nomes de tema — `netflix` 54/89, `dracula` 5/43, `alucard` 1/12, `queroquero` (tema) em globals.css

| Path | Linha(s) | Valor | Variável proposta | Destino |
|---|---|---|---|---|
| `sources/apps/web/styles/globals.css` | blocos `[data-theme="queroquero"]`, `dracula`, `alucard` | temas de marca | `{{PROJECT_THEMES}}` (lista) | C (fonte espelhada como evidência do ds-gate) |
| `sources/.claude/skills/ui-evidence/SKILL.md` | `--themes light,dark,dracula,alucard` | lista de temas da captura | `{{UI_EVIDENCE_THEMES}}` | B |
| `chapters/{01,05,06,09,10,11}` | 1-2 cada | dracula/alucard na narrativa | — | C |
| `netflix*` (chapters 8 arquivos, 54 occ.; sources runs/planos 89 occ.) | — | nome de FORK/maratona (`netflix-ui`, branch, worktree) — não é tema de CSS | — | C (história das maratonas) |

### 2.12 Diretórios de convenção — `.claude/` 536, `docs/` 158, `apps/` 157, `tasks/lessons` 71, `.codex/` 20 (só chapters)

| Path | Valor | Variável proposta | Destino |
|---|---|---|---|
| `verify.py:23` (regex `CITE`) | prefixos hardcoded `(?:\.claude|\.codex|\.githooks|apps|docs|scripts|tasks)/` | `WIKI_SOURCE_PREFIXES` (config do verify) | **A** — é o único código do wiki-raiz que fixa a convenção |
| `verify.py:15-22` (`ALLOW_ABSENT`) | allowlist com paths do learnhouse | `WIKI_MIRROR_ALLOWLIST` (arquivo de config, não inline) | **A** |
| `sources/.claude/settings.json` | todos os comandos usam `$CLAUDE_PROJECT_DIR/.claude/hooks/...`, `scripts/dev-doctor.sh` | `HARNESS_HOOKS_DIR`, `HARNESS_SCRIPTS_DIR` | A (com default = convenção atual) |
| `sources/.claude/hooks/*` | `.claude/runs/.slots`, `.claude/runs/ACTIVE`, `.claude/evidence/`, `tasks/lessons.md` | `HARNESS_RUNS_DIR`, `HARNESS_EVIDENCE_DIR`, `HARNESS_LESSONS_FILE` | A |
| `sources/.claude/loop.md` (Linhas 9-22) | `tasks/lessons.md`, `scripts/docs-wiki-lint.py`, `apps/web/scripts/ds-gate.sh`, `scripts/ref-integrity.py` | `HARNESS_LOOP_CHECKS` (lista parametrizada) | B (loop.md é template por-projeto) |
| chapters (536 occ. `.claude/`) | narrativa | — | C |

**Recomendação explícita:** `.claude/`, `.codex/`, `docs/`, `tasks/` são convenções das FERRAMENTAS (Claude Code exige `.claude/`; Codex exige `.codex/` e `AGENTS.md`) — não parametrizar os dois primeiros além de constantes com default fixo; `docs/` e `tasks/lessons.md` sim são escolha do projeto (`HARNESS_DOCS_DIR`, `HARNESS_LESSONS_FILE`).

## 3. Proposta de config central (nomes explicativos, destino A)

```
# --- identidade ---
PROJECT_NAME=learnhouse             # slug do projeto (prefixo de skills/agents/containers)
PROJECT_ROOT=/home/augusto/code/learnhouse
CLIENT_NAME="Quero-Quero"           # opcional; vazio = sem camada de cliente
CLIENT_PRODUCT_NAME="Quero-Quero Academy"
CLIENT_ORG_SLUG=queroquero
OWNER_NAME=Augusto
GIT_REMOTE_OWNER=gutocarollo
GIT_REMOTE_URL=git@github.com:gutocarollo/queroquero-academy.git

# --- dev stack ---
HARNESS_DEV_API_PORT=1338
HARNESS_DEV_WEB_PORT=3009
HARNESS_DEV_COLLAB_PORT=4000
HARNESS_DEV_DB_PORT=5433
HARNESS_DEV_DB_INTERNAL_PORT=5432
HARNESS_DEV_REDIS_PORT=6379
HARNESS_RESERVED_PORTS=3000         # portas que o dev NÃO pode usar (EasyPanel)
HARNESS_DEV_CONTAINER_PREFIX=${PROJECT_NAME}-   # -db-dev, -redis-dev, -worker-dev, -gotenberg-dev
HARNESS_MCP_DB_DEV_PORT=18114
HARNESS_MCP_DB_PROD_PORT=18115
HARNESS_MCP_PROXY_IMAGE=local/postgres-mcp-proxy:python3.14

# --- prod (todos opcionais; ausentes = sem guardas de prod) ---
PROD_STACK_PREFIX=qq-academy
PROD_PROTECTED_SERVICES="qq-academy cloudflare-tunnel easypanel"
PROD_REGISTRY_URL=localhost:5000
PROD_PUBLIC_WEB_URL=https://qq-academy-web.kj6gzi.easypanel.host
PROD_PUBLIC_API_URL=https://qq-academy-api.kj6gzi.easypanel.host
PROD_HOST_NAME=srv1777233

# --- caps do harness ---
HARNESS_SUBAGENT_MAX_CONCURRENT=6
HARNESS_SUBAGENT_SLOT_STALE_MINUTES=45
HARNESS_LESSONS_INJECT_MAX_LINES=80
HARNESS_UI_EVIDENCE_SKIP_TTL_SECONDS=14400
HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS=300
HARNESS_RUNAWAY_CPU_PCT=50
HARNESS_RUNAWAY_MIN_AGE_SECONDS=3600
HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS=3
HARNESS_PLAN_REVIEW_MAX=2
HARNESS_EXECUTION_REVIEW_MAX=3
HARNESS_ADVERSARIAL_REVIEWER_MODEL=fable
HARNESS_CODEX_MAX_THREADS=4
HARNESS_CODEX_MAX_DEPTH=1
HARNESS_CODEX_PROJECT_DOC_MAX_BYTES=65536

# --- convenções (defaults = padrão das ferramentas; raramente mudar) ---
HARNESS_DOCS_DIR=docs
HARNESS_LESSONS_FILE=tasks/lessons.md
HARNESS_RUNS_DIR=.claude/runs
HARNESS_EVIDENCE_DIR=.claude/evidence

# --- e2e ---
E2E_ADMIN_EMAIL=admin@school.dev
E2E_ADMIN_PASSWORD=admin12345
```

## 4. A decisão A/B/C aplicada (regra de particionamento)

- **A (config central):** todo valor LIDO por script executável em runtime (`sources/scripts/dev-doctor.sh`, `sources/.claude/hooks/*.sh|py`, `verify.py`). São ~25 variáveis, com pouquíssimos pontos de definição — a maioria já está semi-centralizada (ex. `dev-doctor.sh:19`).
- **B (placeholder de template):** artefatos que o framework GERA por projeto no bootstrap: as 12 regras hookify, as ~13 skills, os 4+4 agents (Claude `.md` + Codex `.toml`), `settings.json`, `.codex/config.toml`, `loop.md`, `deliverable-banlist.txt`, `CLAUDE.md` e os índices do wiki (`llms.txt`, `manifest.json`, `README.md`, `SCHEMA.md`, headers de capítulo). O nome do arquivo TAMBÉM é template (`deploy-{{PROD_STACK_PREFIX}}`, `{{PROJECT_NAME}}-delivery-council`).
- **C (exemplo histórico — NÃO templatizar):** o corpo dos 15 capítulos, `sources/docs/**`, `sources/.claude/runs/done/**`, `sources/tasks/lessons.md`, `sources/.claude/contracts/**`. **Decisão de projeto: os capítulos contam a HISTÓRIA do learnhouse (commits, datas, incidentes como os 18 chromium de 2026-07-13, a regra dos 17 subagents de 2026-06-22). Substituir "learnhouse" por `{{PROJECT_NAME}}` nesses textos destruiria a evidência que dá credibilidade ao tutorial.** No framework portátil, os capítulos viram "estudo de caso de referência" e a instância nova gera os SEUS exemplos com o tempo.
- **R (redigir):** `sources/apps/api/.env` Linhas 6-7, 22, 35-39, 41, 44, 48 (segredos vivos) e IPs privados/públicos (`100.98.49.77` em `.env:14`; `187.127.10.14` em `deploy-qq-academy/SKILL.md:21`). Antes de QUALQUER unificação com repos públicos (`gutocarollo/guto-wiki`, `gutocarollo/agent-swarm`), rotacionar as chaves expostas — elas já estão em disco fora do repo original.

## 5. Quantificação consolidada (ocorrências por valor, chapters+meta / sources)

| Valor | ch+meta | sources | Destino dominante |
|---|--:|--:|---|
| `learnhouse` | 115 | 285 | C (narrativa) + B (artefatos) |
| `qq-academy` | 69 | 127 | C + B |
| `Quero-Quero`/`queroquero` | 19 | 98 | C + B |
| `netflix*` (forks/maratonas) | 54 | 89 | C |
| `Augusto`/`augusto` | 77 | 158 | C |
| `.claude/` | 536 | — | C (const. de ferramenta) |
| porta 1338 / 3009 / 5433 | 18/28/19 | 40/46/28 | A (definição) + C (narrativa) |
| 18114/18115 | 8 | 9 | A |
| `cloudflare`/`easypanel`/`kj6gzi`/`srv1777233` | 18 | 146 | B/R |
| `admin@school.dev`+`admin12345` | 3 | 11 | B |
| `fable` | 4 | 23 | A (1 var) + C |
| `dracula`/`alucard` | 6 | 55 | B (lista de temas) + C |
| `gutocarollo` | 8 | 11 | A/B |
| CAP=6 / 45min / MAX_LINES=80 / 14400 / 300s | ~22 | ~10 | A (5 vars) + C |

## 6. Gaps vs. o objetivo "framework portátil" (o que a auditoria revela além do pedido)

1. **Não existe NENHUM arquivo de config central hoje** — cada valor vive no seu script. O `dev-doctor.sh` é o mais próximo de um "single source" (portas na Linha 19) e é o melhor candidato a primeiro consumidor da config.
2. **A regra `model: fable` do reviewer não está materializada em artefato** — vive em RUN.md histórico e na memória (MEMORY.md do learnhouse). O framework deve escrevê-la no frontmatter do agent gerado.
3. **`verify.py` embute a convenção de prefixos (Linha 23) e a allowlist (Linhas 15-22)** — ambos precisam externalizar para o wiki ser gerável para outro projeto.
4. **`SENSITIVE.md` é um relatório manual datado (2026-07-17)** — no framework deve ser SAÍDA de um scanner (os padrões da §2 deste relatório são o seed do scanner).
5. **Nomes de componente carregam o projeto no NOME do arquivo** (`learnhouse-delivery-council`, `deploy-qq-academy`, `run-learnhouse`, `qq-live`, `hookify.qq-prod-*`) — o bootstrap precisa renomear arquivos, não só conteúdo.
