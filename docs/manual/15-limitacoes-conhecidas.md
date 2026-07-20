# 15. Apêndice — limitações conhecidas

Registro honesto do que o framework hoje NÃO cobre, cobre parcialmente, ou cobre com assimetria entre runtimes. Cada item declara o estado real e o workaround. (Itens saem daqui quando resolvidos — este arquivo é living, editado in-place.)

## Plataforma suportada (declarado em M3/H4 — auditoria adversarial)

**Requer GNU/Linux com Bash ≥4, GNU coreutils, `flock` (util-linux) e `python3`.** Antes desta rodada, "portátil" era um adjetivo sem declaração em lugar nenhum do repo — os hooks (`.harness/hooks/`) e scripts (`.harness/lib/`) usam, sem alternativa POSIX: `mapfile`/`declare -A` (Bash ≥4 — o Bash do macOS é 3.2 por licença GPLv3, não atualizado pela Apple), `stat -c` (GNU coreutils; BSD/macOS usa `stat -f`), `date +%s%N` (nanossegundos, GNU-only — BSD `date` não tem `%N`), `flock` (util-linux, Linux — sem equivalente nativo no macOS) e `timeout` (GNU coreutils, uso não-bloqueante).

- **macOS:** não suportado nativamente. Instale `brew install bash coreutils util-linux` e garanta que os binários GNU (ou seus prefixos `g*`: `gstat`, `gdate`, `gtimeout`) precedem os do sistema no `PATH` dos hooks.
- **Windows nativo (sem WSL):** não suportado — use WSL2 (Ubuntu/Debian), que é GNU/Linux de verdade.
- **Containers mínimos** (ex.: `alpine` sem `bash`/`coreutils`/`util-linux` instalados): mesma lacuna — instale os pacotes equivalentes (`apk add bash coreutils util-linux python3`) antes de confiar nos hooks.
- **Preflight:** `bash .harness/lib/check-platform.sh` (materializado em todo projeto instalado, dir neutro incondicional) detecta cada dependência faltante individualmente e imprime o comando de fix — rode antes de confiar nos hooks num ambiente novo. `harness-install.sh` já chama esse preflight automaticamente antes do render (aviso não-bloqueante — a instalação em si é agnóstica de plataforma; só o comportamento dos hooks depois é que degrada). Regressão: `templates/tests/test_check_platform.sh` (prova que uma dependência REALMENTE ausente — ex. `flock` removido do `PATH` — é detectada e reportada, não é um relatório cosmético).
- **Não portado nesta rodada** (declarado, não escondido): os scripts não têm fallback POSIX/BSD automático — a decisão foi declarar o requisito + preflight, não reescrever cada `stat -c`/`date +%s%N`/`flock` para funcionar nos dois mundos. Se algum comando específico ganhar um fallback POSIX trivial no futuro (ex.: trocar `date +%s%N` por `date +%s` quando `%N` não resolve), documentar aqui.

## Assimetrias de runtime (Claude Code × Codex)

1. **`harness-init` só tem invocação nativa no Claude Code.** A skill vive em `.claude/skills/` — um projeto `use_codex=true`/`use_claude=false` não tem como invocá-la por nome; o workaround é chamar os motores diretamente (`python3 .harness/lib/scan_project.py all` + `merge_docs.py`), que são runtime-neutros. Candidata a mover para o diretório de skills dual-runtime (`HARNESS_SKILLS_DIR`).
2. **`deliverable-scrub-gate` depende de path Claude-namespaced.** A banlist vive em `.claude/deliverable-banlist.txt`; num projeto Codex-only o arquivo não é gerado e o hook fica permanentemente fail-open (no-op). O mecanismo não foi generalizado para os dois runtimes.
3. **Eventos sem equivalente no Codex:** `PostToolUseFailure` (coberto por `SubagentStop`, que assume disparo também em falha — suposição documentada no próprio [hooks.json.jinja](<../../templates/{% if use_codex %}.codex{% endif %}/hooks.json.jinja>), não confirmada em doc oficial), `SessionEnd` e `Notification` não existem lá.
4. **Trust de hooks por hash no Codex:** cada edição de um script de `.harness/hooks/` invalida o hash confiado — o usuário reconfirma o trust a cada mudança. Sem workaround; custo operacional documentado.
5. **`completion-gate` lê o formato de transcript do Claude Code.** O parse do tail (`transcript_path`, linhas JSON com `type: assistant`) não foi validado contra o formato de transcript do Codex.

## Contratos que o projeto precisa preencher

6. **`dev-doctor` genérico não sobe a stack.** O framework instala um dev-doctor mínimo ([dev-doctor.sh](../../templates/.harness/hooks/dev-doctor.sh), modos `status`/`reap`, parametrizado pela config central) — mas o modo `up` (SUBIR a stack dev) não existe nele: subir exige conhecer os comandos do projeto (compose, dev servers). Esse conteúdo entra por cima, tipicamente preenchendo a skill `run-<projeto>` (instalada como esqueleto).
7. ~~Loop de manutenção não é materializado.~~ **Resolvido em R5** (plano de resgate §2) — `.claude/loop.md` é gerado sempre que `use_claude=true` (capítulo 08). O que continua não coberto: o *agendamento* (o loop roda via `/loop` do Claude Code sob demanda, não em cron nativo) e a ausência de equivalente no Codex, que não tem comando de loop recorrente — nesse caso o workaround é um cron externo chamando o agente em modo não-interativo com o mesmo checklist.
8. **Motor hookify é dependência externa.** O framework instala as REGRAS `.claude/hookify.*.local.md`; o motor é o plugin hookify do Claude Code. Sem o plugin (ou no Codex, que não o tem), as regras são texto inerte — os hooks de `.harness/hooks/` continuam funcionando (não dependem do hookify).

## Parametrização incompleta

9. ~~Gates de UI assumem um layout específico de app web, sem config.~~ **Corrigido** — `ds-gate-posttool` e `ui-evidence-gate` leem `HARNESS_WEB_APP_DIR` (default `.`) em runtime via `.harness/lib/_tooling_conf.py`, não casam `apps/web` literal. Auto-gated continua valendo (no-op silencioso quando o diretório resolvido não existe), mas o path É configurável — muda `harness_web_app_dir` no questionário/`.harness/harness.conf` e os dois gates seguem o novo diretório sem editar script.
10. ~~`ds-gate-posttool` pressupõe verificadores do projeto.~~ **Corrigido** — o ratchet (`.harness/lib/ds-gate.sh`) e o contrato de pares (`.harness/lib/ds-pairs-check.py`) são SHIPADOS PELO HARNESS (gated por `use_ds_gate`), não fornecidos pelo projeto; o hook chama esses dois scripts diretamente. O que de fato é dado do projeto é o *estado* — a baseline commitada (`.ds-baseline.txt`, dentro do diretório do app web) — não o script que a lê.

## Limites de design herdados (documentados, não bugs)

11. **Mapeamento de campo do hookify é hardcoded por ferramenta conhecida** (`command`, `new_text`, `file_path`...): tool nova ou runtime com schema diferente exige estender o motor do plugin, não é configurável (capítulo 07).
12. **Distribuição como plugin é adiada.** O MVP é repo-native (Copier renderiza os registros). Um empacotamento futuro como plugin do runtime SUBSTITUIRÁ o registro em settings.json — nunca somará (dois registros = todo gate dispara em dobro; a regra anti-double-fire do capítulo 14).
13. **Skills de terceiros portadas como estão.** O pacote de skills de auditoria/segurança (capítulo 09) inclui 10 skills (**69 arquivos** — só o conteúdo; o logo `trail-of-bits-mark.svg` e os `agents/openai.yaml` do upstream NÃO são redistribuídos) copiadas byte-a-byte do [trailofbits/skills](https://github.com/trailofbits/skills) (commit `cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af`, CC BY-SA 4.0). Até H5/B2 desta rodada isso era redistribuído **sem** `LICENSE`/`NOTICE`/inventário de proveniência no repo — a frase antiga deste item ("mantém a proveniência original dos autores") era uma afirmação sem lastro, contradita pela auditoria adversarial que constatou a ausência desses artefatos. Corrigido: a proveniência real (por componente, upstream, commit, licença, byte-idêntico/modificado) está agora em [`PROVENANCE.json`](../../PROVENANCE.json) na raiz do repo, com os créditos exigidos pela CC BY-SA em [`NOTICE`](../../NOTICE). O framework não parametriza nem mantém essas 10 skills — atualizações continuam vindo de re-port manual contra o upstream.
14. **`templates/NOTICE.jinja` não tem regressão automatizada de sincronia.** O NOTICE materializado em todo projeto-alvo (raiz, sempre; seção de skills condicional a `use_claude`) foi testado manualmente nesta rodada (`uvx copier copy . <scratch> --vcs-ref HEAD --data use_claude=true|false`, conferindo o conteúdo renderizado nos dois casos) — mas não existe um `templates/tests/test_*.sh` que falhe automaticamente se a lista de skills de terceiros mudar (skill nova do trailofbits adicionada/removida, `diataxis` alterado) e `templates/NOTICE.jinja` não for atualizado junto. Enquanto isso não existe, quem adicionar/remover uma skill de terceiro nas rodadas futuras precisa lembrar de atualizar `templates/NOTICE.jinja` (e o `NOTICE`/`PROVENANCE.json` da raiz) manualmente — mesmo risco de drift que qualquer doc não tem lint dedicado.

## Auditoria adversarial 2026-07-20 — gaps de instalação brownfield

Uma auditoria de integração isolada (harness × MakersHub, clones limpos) provou que o instalador **não é "brownfield-safe" em sentido absoluto**: retorna `0` mas pode causar perda silenciosa. Correções desta rodada e gaps ainda abertos:

**Corrigidos (com evidência/regressão):**
- **TOML de custom agent inválido** — um comentário `{#- -#}` entre duas chaves comia o newline, gerando `model_reasoning_effort = "high"developer_instructions = """` (tomllib falhava → o agent Codex não carregava). Corrigido (marcador não-stripping); regressão em `test_codex_parity.sh` (d.2) valida TODOS os `.codex/agents/*.toml` + `config.toml` renderizados.
- **Proveniência Trail of Bits** — NOTICE/PROVENANCE afirmavam 79 arquivos e distribuição de logos; a realidade é **69 byte-idênticos, 0 logos, 0 openai.yaml** (contado no repo). Corrigido em `NOTICE`, `PROVENANCE.json` (files_count) e `templates/NOTICE.jinja` (que ainda estava em PT + afirmava incluir o logo).
- **Escrita fora do alvo via symlink** — `harness-install.sh` seguia symlink em `$dest`/parent e escrevia fora do projeto. Corrigido: guarda de containment (`pwd -P` do parent dentro de `TARGET_REAL`; symlink em `$dest` é removido antes do write; contador `skipped (path escaped target)`; repro do `.codex`→externo confirma arquivo externo INTACTO).

**Abertos (arquitetura/decisão — NÃO resolvidos ainda):**
- **Sem manifest de ownership:** colisão fora dos 4 arquivos sensíveis é sobrescrita sem provar que o arquivo era do harness (pode apagar uma skill homônima do usuário). Mitigação atual: aviso no summary + guia `git diff`. Fix real = manifest de instalação.
- **`copier update` em brownfield com instruções git-ignored** apaga o conteúdo próprio do usuário (o merge só sobrevive se os arquivos estão no índice Git). **Recomendação: não usar `copier update` em brownfield até haver E2E que prove o contrário** (ver capítulo 14, seção "Atualizar").
- **Scanner não entende monorepo de subdiretório não-padrão** (ex.: `backend/`+`frontend/` do MakersHub): lê manifestos da raiz → não detecta framework/testes/portas reais. Fix = varredura de subdiretórios.
- **Superfícies centrais podem ficar git-ignored + conflito com Husky** (`core.hooksPath` vs `.husky/`): sem chaining automático. Instalação não-transacional (falha parcial não faz rollback).

Até fechar os abertos, tratar instalação em repo existente como **review-required** (`git diff`), não "sucesso absoluto".

## Como usar este apêndice

Ao instalar num projeto novo, os itens 6-10 são os que tipicamente pedem ação sua (preencher a skill de subir a stack, decidir o loop, ter o plugin hookify, adaptar os gates de UI ao seu layout). Os demais são custos operacionais a conhecer. Encontrou uma limitação não listada? O lugar dela é aqui — e o ciclo do capítulo 12 (lição → regra) é o caminho para ela não morder duas vezes.
