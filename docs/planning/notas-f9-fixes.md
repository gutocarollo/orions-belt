# F9-fixes — rodada de correção do review adversarial final (engenharia)

> Contexto: o revisor adversarial (fable) deu `CORRIGIR` com 1 gap ALTA + 5 MEDIA +
> 3 BAIXA, e o dono reforçou o requisito central: **o harness é 100% genérico — zero
> conteúdo do repo-doador no produto renderizado**. Esta nota cobre a parte de
> ENGENHARIA (templates/, copier.yml); a generalização da documentação do framework
> (docs/manual/, remoção do case-study/, README/llms.txt/SCHEMA da raiz) correu em
> paralelo por outro executor e não é coberta aqui.

## F1 (ALTA) — AGENTS.md.jinja gerava afirmações falsas e marca de cliente

Todos os achados do revisor confirmados no arquivo antes de corrigir:

- **Hash de grafo do doador afirmado como atual** (linha ~75): bloco understand-anything
  inteiro era INCONDICIONAL (os hooks/skills do mesmo feature já eram gateados por
  `harness_understand_apps_root` — inconsistência interna). Fix: bloco inteiro gateado
  por `{% if harness_understand_apps_root %}`, hash fixo REMOVIDO (regra passa a ser
  "leia sempre de meta.json"), paths parametrizados (`--relative={{ harness_understand_apps_root }}`).
- **Marca do cliente no kit** (`--qq-green-*`, `data-theme queroquero/dracula`): bloco
  DTCG generalizado — "tokens crus da marca do projeto (ex.: `--brand-50..950`)",
  "MARCA (`data-theme` por marca do projeto)"; guardas de DS viraram descrição genérica
  do mecanismo (validação de pares + ratchet) em vez de paths de scripts do doador.
- **Bloco Dropdown**: era o componente/arquivo/botão de OUTRO produto. Virou PRINCÍPIO
  ("defina UM componente canônico e registre o path AQUI") mantendo só o conhecimento
  transferível (anti-pattern `scaleY`, clip-path+translateY+opacity, reduced-motion,
  `grid-rows-[0fr→1fr]` para inline).
- **Bloco Charts**: citava decisão/data do dono, outro projeto (makershub) e 2 skills
  que o template nem instala. Virou princípio "1 biblioteca canônica + cláusula de
  fallback honesta + protótipo ≠ produção".
- **Contradição `project_doc_max_bytes = 65536` vs render 32768**: texto agora usa
  `{{ harness_codex_project_doc_max_bytes }}` (e `max_threads`/`max_depth` idem).
  Confirmado empiricamente que as variáveis com `when: use_codex` caem no DEFAULT
  quando `use_codex=false` (render claude-only imprime 32768, não crash).
- **"máximo 6 simultâneos"** → `{{ harness_subagent_max_concurrent }}` (2 ocorrências,
  §11 e §15). **"Augusto"** → `{{ owner_name }}` (§16 e heading "File paths for").
  `.claude/runs/` → `{{ harness_runs_dir }}`. Caps de rodada do council no corpo e no
  bloco ARGS → `{{ harness_plan_review_max }}`/`{{ harness_execution_review_max }}`.
- **Header de proveniência**: era `{% raw %}<!-- ... -->{% endraw %}` (RENDERIZAVA no
  projeto-alvo citando learnhouse/qq-green). Virou comentário Jinja `{#- -#}` —
  proveniência vive no source do framework, nunca no render.
- Varredura do arquivo inteiro além dos pontos citados: bloco ui-evidence gateado por
  `use_ui_evidence` + temas `{{ harness_ui_evidence_themes }}` (sem dracula/alucard);
  bloco wiki sem legado do doador (`design-system-wiki-ingest` etc.); §9.2 sem a rule
  de outro projeto (MakersHub); §10 sem data de decisão do doador.

## Sweep de genericidade (regra do dono: zero termo do doador no RENDER)

`grep -riE "learnhouse|quero|qq-|queroquero|dracula|alucard|augusto|kj6gzi|5b125ff9"`
sobre o render com defaults tinha ~30 arquivos com hit. Padrões corrigidos:

- **Proveniência em .jinja** (council, adversarial-review, reviewer .toml): blocos
  `{% raw %}<!-- -->{% endraw %}`/comentário TOML → comentário Jinja (não renderiza).
- **Proveniência em arquivos planos** (que copiam verbatim: scan_project.py,
  merge_docs.py, _tooling_conf.py, subagent-throttle.sh, lessons-inject, lei-zero,
  ds-gate, seeds docs/SCHEMA+log+lessons, banlist, skills com linha "Origem:"):
  "learnhouse"/"Augusto" → "harness-doador de referência"/"o dono do harness-doador".
- **IDs de componente do classificador**: `hookify.qq-prod-*` → `hookify.prod-*`
  (scan_project.py + test_scan_project.py) — o `qq-` era naming do doador.
- **Skill diataxis (terceiro)**: 5 paths Windows pessoais (`C:\Users\...\makershub\...`)
  → nota neutra "snapshot local do curador original (path removido do kit genérico)".
- **Falso-positivo semântico real**: ref-integrity dizia "quero achar refs órfãs"
  (verbo português) — o gate grep é burro e pega `quero`; reescrito "preciso achar".
- **Armadilha de teste descoberta**: renderizar para um scratch dir cujo PATH contém
  "learnhouse" (o scratchpad da sessão) gera falsos-positivos via `{{ project_root }}`
  — o gate deve renderizar para path neutro (usado /tmp/f9-render*).

Resultado: grep ZERO em todos os 4 cenários (defaults, claude-only, codex-only,
prod+understand+e2e), incluindo `65536`.

## F2 (MEDIA) — variáveis-fachada ligadas (nenhuma removida sem consumidor)

- `harness_plan_review_max`/`harness_execution_review_max`: council SKILL.md.jinja
  usava 2/3 hardcoded em 12 pontos (ARGS, defaults, limites, "máximo de N rodadas",
  sentinels `N/N` e `<rodadas>/N`) → todos viraram variáveis. `test_council_merge.py`
  atualizado para assertar a forma TEMPLATE (o teste lê o .jinja cru) — mudança
  consciente e documentada no próprio teste; witness (marcadores load-bearing) não
  pinava os números, só os sentinels de handoff — inalterado e verde.
- `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS`: marathon-stop-gate.sh lia `-ge 3`
  fixo → lê da config via `_tooling_conf.py` (fail-open p/ 3).
- `harness_adversarial_reviewer_model`: consumida no frontmatter `model:` do agent
  Claude `{{ project_name }}-adversarial-reviewer.md.jinja`. **Não** inventado campo
  equivalente no .toml Codex — o custom agent real do doador não declara `model`
  (só `model_reasoning_effort`), não fabricar chave sem evidência de suporte.
- `harness_reap_chromium_max_age_seconds`/`harness_runaway_cpu_pct`/
  `harness_runaway_min_age_seconds`: consumidas pelo dev-doctor novo (F3) — mantidas.

## F3 (MEDIA) — dev-doctor.sh genérico (referência morta eliminada)

`settings.json.jinja` e `hooks.json.jinja` apontavam para `scripts/dev-doctor.sh`,
que o framework nunca instalou (referência morta em TODO projeto-alvo); e
`reap-leaks.sh` chamava o mesmo path morto (o reap do Stop hook era um no-op
silencioso — `|| true` mascarava). Novo `templates/.harness/hooks/dev-doctor.sh`
GENÉRICO (estrutura do original do doador, lido como referência):

- `status`: portas de `HARNESS_DEV_{API,WEB,COLLAB,DB,REDIS}_PORT` abertas (ss com
  fallback /dev/tcp; porta 0/ausente = pula), containers com
  `HARNESS_DEV_CONTAINER_PREFIX` (se docker existir; filtro é substring do docker),
  WARN de runaway. Exit 0 SEMPRE (SessionStart informativo).
- `reap`: tooling órfão PPID 1 (serena/mcp/playwright-mcp) + chromium headless
  vazado (órfão OU idade > `HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS`) + WARN runaway
  (`HARNESS_RUNAWAY_CPU_PCT`/`HARNESS_RUNAWAY_MIN_AGE_SECONDS`). Exit 0 sempre.
- Modo `up` do original NÃO portado (subir stack exige conhecer comandos do projeto
  — conteúdo do projeto-alvo, não do framework).
- Testado ao vivo contra fixture com a config desta VPS: detectou DB :5433/Redis
  :6379 UP, API :1338 DOWN (verdadeiro — não está rodando), containers por prefixo,
  reap 0 (sem leaks no momento), fail-open sem conf.

## F4 (MEDIA) — marathon hooks respeitam HARNESS_RUNS_DIR

`marathon-reinject.sh`, `marathon-precompact.sh`, `marathon-stop-gate.sh` liam
`.claude/runs/` fixo → leem `HARNESS_RUNS_DIR` via `_tooling_conf.py` (fail-open
p/ `.claude/runs`). NOTA de escopo: `subagent-throttle.sh`/`subagent-release.sh`
continuam com `.claude/runs/.slots` fixo — fora do escopo nominal desta rodada
(coordenador listou os 3 marathon); candidato à mesma normalização depois.

## F6 (MEDIA) — flags por módulo (D5) + despersonalização

- Novas perguntas no copier.yml: `use_ui_evidence` e `use_icon_guard` (bool, default
  true — comportamento anterior preservado; help explica quando desligar). O
  harness-init passa a poder setá-las via `--data` conforme o relatório de
  aplicabilidade.
- Gateados por `use_ui_evidence`: skill `ui-evidence`, hook físico
  `ui-evidence-gate.sh`, registro Stop nos DOIS runtimes (settings.json.jinja +
  hooks.json.jinja), bloco correspondente no AGENTS.md. Com a flag off: nenhum
  artefato nem registro (testado, JSON válido nos dois lados).
- `hookify.icones-lucide`: gateada por `use_icon_guard` (filename condicional) e
  despersonalizada — sem "Augusto", sem números da migração do doador, sem path
  `apps/web` no matcher (agora `\.(tsx|jsx)$`); a mensagem instrui a EDITAR a regra
  se a lib canônica do projeto for outra.

## F7/F8/F9 (BAIXA)

- **F7**: harness-init/SKILL.md tinha a seção "Gap conhecido" inserida NO MEIO da
  frase final do Passo 6 ("— é o gate" ... "formal desta skill)." órfão no fim do
  arquivo). Frase reconstituída, seção reposicionada depois dela.
- **F8**: `project_root` — testado de verdade: `_copier_conf.dst_path` é
  `PurePosixPath` SEM `.absolute()` e não existe filtro `abspath` no Jinja do Copier
  9.17 (ambos tentados, erro real colado no teste). Não há como normalizar no
  template → aplicada a alternativa do coordenador: help do copier.yml agora declara
  que o valor pode vir relativo em `copier copy` direto, que o harness-init o
  preenche absoluto (scan_project.py `answers` já emite absoluto), e que NENHUM
  hook/script lê esse valor para resolver path.
- **F9**: regex duplicada no prod-destroy quando `prod_protected_services` ==
  `prod_stack_prefix` (default) — dedupe via `{% set %}` + filtro `unique` (builtin
  Jinja; `split` NÃO é filtro Jinja — usado método Python `.split()`). Verificado nos
  2 casos: default → `(acme-stack)`; com extras → `(acme-stack|cloudflared|traefik)`.

## Gates rodados (comando + resultado no relatório da sessão)

1. Regressão: docs_wiki_lint (FAIL só em `docs/manual/*` — trabalho em curso do
   executor PARALELO de docs, fora do meu escopo; zero achado nos meus arquivos),
   ref_integrity --selftest PASS, hook fixture F0 PASS, validate_contract 16 testes
   OK, council merge 7/7, scan+merge 19/19, harness-init e2e 10/10.
2. 4 cenários copier (defaults / claude-only / codex-only / prod+understand+e2e):
   exit 0, JSON válido nos dois runtimes, artefatos condicionais corretos.
3. Grep de genericidade: ZERO hits nos 4 renders (path de destino NEUTRO — ver
   armadilha do scratchpad acima).
4. `test_copier_update_e2e.sh`: 12/12 (tags v0.1.0-v0.3.0 intactas).
