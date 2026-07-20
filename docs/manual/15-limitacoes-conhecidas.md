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

1. ~~`harness-init` só tinha invocação nativa no Claude Code.~~ **Corrigido:** a mesma fonte renderiza byte-idêntica em `.claude/skills/harness-init` e `.agents/skills/harness-init`; `run-<projeto>` e o adapter `deploy-*` Swarm também são gerados nas duas superfícies quando suas capabilities estão configuradas.
2. **`deliverable-scrub-gate` depende de path Claude-namespaced.** A banlist vive em `.claude/deliverable-banlist.txt`; num projeto Codex-only o arquivo não é gerado e o hook fica permanentemente fail-open (no-op). O mecanismo não foi generalizado para os dois runtimes.
3. **Eventos sem equivalente no Codex:** `PostToolUseFailure` (coberto por `SubagentStop`, que assume disparo também em falha — suposição documentada no próprio [hooks.json.jinja](<../../templates/{% if use_codex %}.codex{% endif %}/hooks.json.jinja>), não confirmada em doc oficial), `SessionEnd` e `Notification` não existem lá.
4. **Trust de hooks por hash no Codex:** cada edição de um script de `.harness/hooks/` invalida o hash confiado — o usuário reconfirma o trust a cada mudança. Sem workaround; custo operacional documentado.
5. **`completion-gate` lê o formato de transcript do Claude Code.** O parse do tail (`transcript_path`, linhas JSON com `type: assistant`) não foi validado contra o formato de transcript do Codex.

## Contratos que o projeto precisa preencher

6. **`dev-doctor` genérico não sobe a stack.** O framework instala um dev-doctor mínimo ([dev-doctor.sh](../../templates/.harness/hooks/dev-doctor.sh), modos `status`/`reap`). A skill `run-<projeto>` só é gerada quando `harness_run_command` recebe um comando canônico real; vazio mantém a capability desabilitada, sem esqueleto executável baseado em `apps/web`/`apps/api` presumidos.
7. ~~Loop de manutenção não é materializado.~~ **Resolvido em R5** (plano de resgate §2) — `.claude/loop.md` é gerado sempre que `use_claude=true` (capítulo 08). O que continua não coberto: o *agendamento* (o loop roda via `/loop` do Claude Code sob demanda, não em cron nativo) e a ausência de equivalente no Codex, que não tem comando de loop recorrente — nesse caso o workaround é um cron externo chamando o agente em modo não-interativo com o mesmo checklist.
8. **Motor hookify é dependência externa.** O framework instala as REGRAS `.claude/hookify.*.local.md`; o motor é o plugin hookify do Claude Code. Sem o plugin (ou no Codex, que não o tem), as regras são texto inerte — os hooks de `.harness/hooks/` continuam funcionando (não dependem do hookify).

## Parametrização incompleta

9. ~~Gates de UI assumem um layout específico de app web, sem config.~~ **Corrigido** — `ds-gate-posttool` e `ui-evidence-gate` leem `HARNESS_WEB_APP_DIR` (default `.`) em runtime via `.harness/lib/_tooling_conf.py`, não casam `apps/web` literal. Auto-gated continua valendo (no-op silencioso quando o diretório resolvido não existe), mas o path É configurável — muda `harness_web_app_dir` no questionário/`.harness/harness.conf` e os dois gates seguem o novo diretório sem editar script.
10. ~~`ds-gate-posttool` pressupõe verificadores do projeto.~~ **Corrigido** — o ratchet (`.harness/lib/ds-gate.sh`) e o contrato de pares (`.harness/lib/ds-pairs-check.py`) são SHIPADOS PELO HARNESS (gated por `use_ds_gate`), não fornecidos pelo projeto; o hook chama esses dois scripts diretamente. O que de fato é dado do projeto é o *estado* — a baseline commitada (`.ds-baseline.txt`, dentro do diretório do app web) — não o script que a lê.

## Limites de design herdados (documentados, não bugs)

11. **Mapeamento de campo do hookify é hardcoded por ferramenta conhecida** (`command`, `new_text`, `file_path`...): tool nova ou runtime com schema diferente exige estender o motor do plugin, não é configurável (capítulo 07).
12. **Distribuição como plugin é adiada.** O MVP é repo-native (Copier renderiza os registros). Um empacotamento futuro como plugin do runtime SUBSTITUIRÁ o registro em settings.json — nunca somará (dois registros = todo gate dispara em dobro; a regra anti-double-fire do capítulo 14).
13. **Skills de terceiros portadas como estão.** O pacote de auditoria/segurança (capítulo 09) inclui 10 skills e **69 arquivos de conteúdo** copiados byte-a-byte do [trailofbits/skills](https://github.com/trailofbits/skills) (commit `cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af`, CC BY-SA 4.0). Foram omitidos **10 `trail-of-bits-mark.svg`** e **10 `agents/openai.yaml`**, um de cada por skill. Até H5/B2 isso era redistribuído sem `LICENSE`/`NOTICE`/inventário; agora [`PROVENANCE.json`](../../PROVENANCE.json) e [`NOTICE`](../../NOTICE) registram upstream, commit, licença, contagens e exclusões. O framework não mantém automaticamente essas skills: atualizações continuam vindo de re-port manual contra o upstream.
14. **`templates/NOTICE.jinja` não tem regressão automatizada de sincronia.** O NOTICE materializado em todo projeto-alvo (raiz, sempre; seção de skills condicional a `use_claude`) foi testado manualmente nesta rodada (`uvx copier copy . <scratch> --vcs-ref HEAD --data use_claude=true|false`, conferindo o conteúdo renderizado nos dois casos) — mas não existe um `templates/tests/test_*.sh` que falhe automaticamente se a lista de skills de terceiros mudar (skill nova do trailofbits adicionada/removida, `diataxis` alterado) e `templates/NOTICE.jinja` não for atualizado junto. Enquanto isso não existe, quem adicionar/remover uma skill de terceiro nas rodadas futuras precisa lembrar de atualizar `templates/NOTICE.jinja` (e o `NOTICE`/`PROVENANCE.json` da raiz) manualmente — mesmo risco de drift que qualquer doc não tem lint dedicado.

## Auditoria adversarial 2026-07-20 — gaps de instalação brownfield

Uma auditoria de integração isolada (harness × MakersHub, clones limpos) provou que a **versão anterior** do instalador não era "brownfield-safe" em sentido absoluto: retornava `0` mas podia causar perda silenciosa. Correções desta rodada e gaps ainda abertos:

**Corrigidos (com evidência/regressão):**
- **TOML de custom agent inválido** — um comentário `{#- -#}` entre duas chaves comia o newline, gerando `model_reasoning_effort = "high"developer_instructions = """` (tomllib falhava → o agent Codex não carregava). Corrigido (marcador não-stripping); regressão em `test_codex_parity.sh` (d.2) valida TODOS os `.codex/agents/*.toml` + `config.toml` renderizados.
- **Proveniência Trail of Bits** — NOTICE/PROVENANCE afirmavam 79 arquivos e distribuição de logos; a realidade é **69 arquivos byte-idênticos distribuídos, 10 logos omitidos e 10 `agents/openai.yaml` omitidos**. Corrigido em `NOTICE`, `PROVENANCE.json`, `templates/NOTICE.jinja` e capítulo 09.

**Corrigidos nesta arquitetura:**
- `.harness/install-manifest.json` prova ownership de arquivo inteiro por hash; colisão desconhecida e edição local abortam antes de escrever. As quatro superfícies compartilhadas usam merge semântico.
- O planner fixa a raiz por descritor Linux, rejeita raiz/destino/ancestral symlink, path inseguro e arquivo não regular antes da mutação. Lock por alvo impede dois instaladores simultâneos. Journal + backups restauram falha controlada; após interrupção de processo, a recuperação só reverte estados que ainda coincidam com o hash anterior ou com o hash escrito pela transação, recusando sobrescrever edição posterior.
- O scanner faz descoberta limitada de workspaces, diretórios convencionais e raízes explícitas, sem `rglob` irrestrito nem traversal de symlink; expõe evidência e confiança por componente.
- Husky não é deslocado. `--chain-hooks` faz chaining idempotente e explícito; sem consentimento, o instalador avisa e deixa o manager intacto.

**Abertos por política/escopo, não escondidos:**
- Não há prune automático: paths removidos upstream ficam `orphaned` e preservados.
- Um path marcado `preserve` não recebe updates do harness; reverter essa decisão ainda exige edição/ação de ownership futura.
- Atomicidade é por arquivo com recuperação, não uma transação global nem garantia de power-loss durability; hooks/Husky e baseline de DS são pós-tarefas fora do rollback dos arquivos. `--chain-hooks` explícito valida o bloco completo e propaga falha por exit não-zero, mas não desfaz a aplicação já concluída.
- `copier update` nativo continua proibido após adoção brownfield; repetir `harness-install.sh` é o updater suportado.
- Deploy só gera skill/guardas mutantes para `prod_deployment_driver=swarm-direct`. EasyPanel fica fail-closed até existir adapter próprio.
- O UI evidence valida estrutura/CRC/pixels/hash, mas não atesta criptograficamente que o PNG veio do Playwright; quem controla simultaneamente o working tree e o diretório de evidência pode fabricar um par PNG+manifest válido.

Instalação em repo existente continua **review-required**, mas colisões e escapes agora falham fechados em vez de depender somente de `git diff` posterior.

## Como usar este apêndice

Ao instalar num projeto novo, os itens 6-10 são os que tipicamente pedem ação sua (preencher a skill de subir a stack, decidir o loop, ter o plugin hookify, adaptar os gates de UI ao seu layout). Os demais são custos operacionais a conhecer. Encontrou uma limitação não listada? O lugar dela é aqui — e o ciclo do capítulo 12 (lição → regra) é o caminho para ela não morder duas vezes.
