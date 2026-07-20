# 06. Os porteiros do fim de turno — Stop hooks e o PreCompact irmão

Hooks de `Stop` rodam quando o agente quer **encerrar o turno** — o último checkpoint antes de a resposta final chegar ao usuário. É o lugar dos gates que auditam o TRABALHO INTEIRO do turno, não uma ação isolada: houve claim de conclusão sem prova? mudou UI sem evidência visual? a execução longa foi abandonada no meio? sobrou processo vazado?

O contrato de todos: `exit 2` + stderr bloqueia a parada (a mensagem volta para o agente, que precisa resolver e tentar encerrar de novo); o campo `stop_hook_active` do JSON do evento indica que o hook JÁ bloqueou uma vez neste turno — todos os porteiros liberam nesse caso, prevenindo loop infinito de bloqueio.

O framework registra quatro Stop hooks e um `PreCompact` irmão.

## completion-gate — claim de conclusão exige bloco de evidência

**O que é** — [templates/.harness/hooks/completion-gate.py](../../templates/.harness/hooks/completion-gate.py). O anti-overclaim: a tendência do agente de declarar "100% executado", "tudo corrigido", "pronto para produção" sem evidência verificável. A regra que ele enforça: qualquer claim de conclusão **de nível de plano** exige o bloco de evidência da skill `prova-de-conclusao` (capítulo 09), terminando na linha-sentinela literal `PROVA-DE-CONCLUSAO: <x>/<y> PASS, gaps: [...]`.

**O que faz** —
1. Lê o tail do transcript da sessão (via `transcript_path` do JSON; só os últimos 2 MB — transcripts crescem a dezenas de MB) e extrai as últimas mensagens do assistente do loop principal (ignora sidechains de subagents).
2. Testa a ÚLTIMA mensagem contra a regex de claims de plano: `100%`, "plano executado/concluído", "tudo corrigido/implementado", "todos os itens fechados", "pronto para produção/homolog/deploy", "gaps zerados", "implementação completa". Claims de mudança única ("arquivo corrigido") passam de propósito — para esses vale a skill `verify`, não o gate.
3. Se casou claim: procura a sentinela `PROVA-DE-CONCLUSAO: n/m` nas 3 últimas mensagens (o veredito pode estar na mensagem anterior ao resumo). Ausente ⇒ `exit 2` com a instrução: rodar a skill, montar a tabela de evidência POR ITEM (comando + exit code, grep com path e linha, contagem de testes, manifest de evidência visual), ou **reformular o veredito sem o claim** — fabricar certeza é a violação máxima; declarar gap é sempre legítimo.

```mermaid
flowchart TD
    A["agente quer encerrar o turno"] --> B{"stop_hook_active?"}
    B -- "sim" --> Z["libera (ja bloqueou 1x)"]
    B -- "nao" --> C["le tail do transcript; ultima mensagem do assistente"]
    C --> D{"casa claim de conclusao de PLANO?"}
    D -- "nao" --> Z2["libera"]
    D -- "sim" --> E{"sentinela PROVA-DE-CONCLUSAO nas 3 ultimas mensagens?"}
    E -- "sim" --> Z2
    E -- "nao" --> F["BLOQUEIA: rode a skill prova-de-conclusao ou reformule sem o claim"]
```

**Exemplo (cenário simulado)** — Numa sessão de correção de bugs no repositório `demo-app`, o agente termina o turno com a frase "Todos os itens do plano foram corrigidos, pronto para produção." sem ter rodado a skill `prova-de-conclusao` nas mensagens anteriores. O `completion-gate` casa a frase contra a regex de claim de plano, procura a sentinela `PROVA-DE-CONCLUSAO:` nas 3 últimas mensagens e não encontra — bloqueia com `exit 2` e devolve: "rode a skill prova-de-conclusao ou reformule o veredito sem o claim". Na tentativa seguinte, o agente roda os testes reais (`npm test`, exit 0, 12/12), faz o grep dos itens corrigidos com path e linha, monta a tabela por item e escreve `PROVA-DE-CONCLUSAO: 5/5 PASS, gaps: []` — a parada é liberada.

**Como configurar** — Sem variáveis; regexes fixas (o vocabulário de overclaim é o mesmo em qualquer projeto). O par declarativo é a skill `prova-de-conclusao`.

## ui-evidence-gate — mudança de UI exige pixel renderizado

**O que é** — [ui-evidence-gate.sh](<../../templates/.harness/hooks/{% if use_ui_evidence %}ui-evidence-gate.sh{% endif %}.jinja>), gerado quando o módulo de evidência visual é ativado explicitamente (`use_ui_evidence`, default `false`; o `harness-init` recomenda somente quando detecta frontend renderizável + Playwright). A regra: trabalho de UI só é "pronto" com evidência RENDERIZADA (screenshot + manifest), nunca com diff de código — diff não prova que a tela ficou certa. O motivo é concreto, não teórico: revisão só por diff já deixou passar bugs que só existem no pixel — texto invisível porque herdou a cor errada do tema, borda que regride depois de já ter sido corrigida mais de uma vez, ou animação de transição imperceptível ou ausente. Nenhum desses aparece numa listagem de linhas alteradas. O gate bloqueia o fim do turno quando há mudança de UI no working tree sem evidência mais recente que a mudança.

**O que faz** —
1. Resolve o app configurado por `HARNESS_WEB_APP_DIR` e coleta `.tsx|.css` alterados em `{app,components,styles}`; deleção usa o mtime do diretório pai para não desaparecer da prova.
2. Escape hatch: se existir `<HARNESS_EVIDENCE_DIR>/SKIP` com idade menor que `HARNESS_UI_EVIDENCE_SKIP_TTL_SECONDS`, libera — é a válvula para mudança comprovadamente não-visual ou stack fora do ar, com o motivo declarado no veredito. O TTL impede o SKIP de virar permanente.
3. Procura um manifest posterior à mudança e valida `captures > 0`, paths relativos/contidos, PNG completo (chunks/CRC/IHDR/IDAT/IEND + stream de pixels decodificável) e SHA-256 de cada imagem. JSON forjado, assinatura PNG truncada, path traversal ou hash divergente não liberam o gate.

Esse controle prova consistência estrutural do artefato, não *attestation* criptográfica da origem. Um agente malicioso com escrita no projeto ainda pode fabricar um PNG válido e seu manifest/hash; o gate foi desenhado contra evidência ausente, truncada ou acidentalmente inconsistente, não contra o mesmo principal que controla código e evidência.

**Threat model honesto:** o gate prova integridade estrutural e consistência entre arquivos, manifest e tempo da mudança; ele não é atestação criptográfica de que um agente malicioso abriu a rota correta. Um agente com escrita no repo ainda pode fabricar um PNG válido e um manifest coerente. A revisão humana deve olhar os pixels, e ambientes que exigem autoria forte precisam assinar o manifest fora do processo do agente/CI confiável.

```mermaid
flowchart TD
    A["Evento Stop: agente quer encerrar o turno"] --> B{"stop_hook_active ou python3 ausente?"}
    B -- "sim" --> Z["exit 0 — parada permitida"]
    B -- "não" --> C["Diff + untracked no HARNESS_WEB_APP_DIR configurado — só .tsx e .css"]
    C --> D{"Algum arquivo de UI alterado?"}
    D -- "não" --> Z
    D -- "sim" --> E["Calcula o mtime mais novo entre os arquivos alterados"]
    E --> F{"SKIP existe com idade menor que o TTL configurado?"}
    F -- "sim" --> Z
    F -- "não" --> G{"Algum manifest.json no diretório de evidência é mais novo que a mudança?"}
    G -- "sim" --> V{"paths contidos + PNG real + SHA confere?"}
    V -- "sim" --> Z
    V -- "não" --> H
    G -- "não" --> H["stderr: rode a skill ui-evidence ou toque o SKIP com motivo declarado"]
    H --> I["exit 2 — parada bloqueada"]
```

**Exemplo (cenário simulado)** — Com `HARNESS_WEB_APP_DIR=frontend`, o agente ajusta `frontend/components/ui/badge.tsx` e tenta encerrar o turno. O gate encontra a mudança e rejeita tanto ausência de manifest quanto `fake.png` renomeado: só libera depois que `npm run ui:evidence -- after --routes /` produz PNG com assinatura e hash registrados no manifest (ou após um `SKIP` recente com motivo declarado).

**Como configurar** — `use_ui_evidence` (gera ou não o módulo), `HARNESS_EVIDENCE_DIR` (default `.claude/evidence`), `HARNESS_UI_EVIDENCE_SKIP_TTL_SECONDS` (default 14400 = 4h) e `HARNESS_UI_EVIDENCE_THEMES` (CSV de temas que a skill captura; default `light,dark`).

## marathon-stop-gate — execução longa não é abandonada em silêncio

**O que é** — [templates/.harness/hooks/marathon-stop-gate.sh](../../templates/.harness/hooks/marathon-stop-gate.sh). Quando há uma maratona ativa (capítulo 08), o agente não pode simplesmente parar no meio: o gate compara o checklist do `RUN.md` com a tentativa de parada.

**O que faz** — Sem `<HARNESS_RUNS_DIR>/ACTIVE`: inerte. Com maratona ativa: se o checklist tem itens abertos (`- [ ]`), bloqueia devolvendo a "Próxima ação" registrada. Paradas legítimas: checklist zerado, ou a seção "Próxima ação" começando com `AGUARDANDO:` (bloqueado em decisão do usuário). **Anti-prisão**: `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS` bloqueios consecutivos (default 3) SEM o `RUN.md` mudar (o mtime é o detector de progresso) ⇒ libera com aviso — o gate cobra progresso, não mantém refém.

**Exemplo (cenário simulado)** — Numa maratona ativa no projeto `demo-app`, o checklist do `RUN.md` ainda tem 2 itens abertos e a "Próxima ação" não começa com `AGUARDANDO:`. O agente tenta encerrar o turno assim mesmo; o gate bloqueia, incrementa o contador de strikes e devolve a "Próxima ação" registrada. Se isso se repetir por `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS` vezes seguidas sem o mtime do `RUN.md` mudar — sinal de que nada avançou de verdade —, o gate desiste de insistir, zera os strikes e libera a parada com um aviso de sistema. A maratona segue `ACTIVE`, mas o agente não fica preso num loop de bloqueios inúteis.

## reap-leaks — processos vazados não acumulam entre turnos

**O que é** — [templates/.harness/hooks/reap-leaks.sh](../../templates/.harness/hooks/reap-leaks.sh). Tooling de agente vaza processos: navegadores headless lançados por scripts de screenshot sem teardown, dev-servers órfãos. Acumulados, degradam a máquina (memória/swap) sessão após sessão. Este hook roda a colheita a cada fim de turno.

Este hook nasce de um mecanismo real, não de teoria: um servidor de automação acumulou dezenas de navegadores headless vazados de scripts que quebravam antes do teardown, o swap encheu e a máquina ficou lenta para o resto do trabalho. O detalhe que importa não é o incidente em si, é a causa raiz: a limpeza já existia como comando manual, mas cobria só o padrão previsto (processos de tooling de agente com nome reconhecível) — o vazamento real era um navegador headless CRU, fora desse padrão, e ninguém rodava o comando porque nada o disparava sozinho. Daí o hook: fecha os dois buracos ao mesmo tempo, amplia a detecção e a liga a um evento determinístico.

**O que faz** — Delega ao modo `reap` do [dev-doctor genérico](../../templates/.harness/hooks/dev-doctor.sh), mas nunca descobre nem mata processos globalmente. Um launcher que deseja limpeza automática registra `<pid> <start_ticks> <reap_after_epoch>` em `<HARNESS_PID_REGISTRY_DIR>/<nome>.pid`. Antes de enviar `TERM`, o reaper prova simultaneamente: registry contido no projeto, entrada regular não-symlink, lease expirada, PID ainda existente, start-time igual (proteção contra reúso de PID), cwd vivo dentro da raiz e comando reconhecido como tooling de agente/headless. Registro prova ownership; só a expiração explícita prova autorização de cleanup. Entrada inválida, lease ativa, processo externo ou comando não reconhecido gera apenas WARN. Processo de alta CPU e vida longa também gera só WARN.

O trade-off é deliberado: sem registro explícito, um leak real não será morto automaticamente. Em troca, um Chromium/Playwright pertencente a outro projeto ou outra sessão não pode ser derrubado apenas por casar nome, idade ou flag `--headless`.

```mermaid
flowchart TD
    A["Evento Stop: fim de qualquer turno"] --> B["Chama o modo reap do dev-doctor"]
    B --> C{"Existe entrada no registry local do projeto?"}
    C -- "não" --> G{"Runaway: CPU acima do limite e vida acima do mínimo configurado?"}
    C -- "sim" --> D{"PID + start-time + cwd + comando provam ownership?"}
    D -- "sim" --> X{"lease reap_after_epoch expirou?"}
    X -- "sim" --> E["TERM apenas no PID registrado"]
    X -- "não" --> F
    D -- "não" --> F["WARN; não mata"]
    E --> G
    F --> G
    G -- "sim" --> H["Só WARN — não mata, pode ser servidor legítimo"]
    G -- "não" --> I["Nada a fazer"]
    H --> J{"Reapou algum processo nesta passada?"}
    I --> J
    J -- "sim" --> K["Imprime reap-leaks: com as linhas do que foi reapado"]
    J -- "não" --> L["Silêncio total"]
    K --> Z["exit 0 sempre — nunca bloqueia a parada"]
    L --> Z
```

**Exemplo (cenário simulado)** — Um launcher do projeto `demo-app` inicia Playwright, lê o field 22 de `/proc/<pid>/stat` e grava `<pid> <start_ticks> <reap_after_epoch>` em `.harness/pids/ui-evidence.pid`. Antes desse instante, o Stop hook preserva o processo mesmo com ownership válida. Depois da expiração, confirma que o mesmo processo ainda roda com cwd dentro de `demo-app` e comando Playwright/headless, envia `TERM`, remove a entrada consumida e contabiliza um reap. Sem o arquivo, com start-time divergente ou cwd em outro clone, não mata.

**Como configurar** — `HARNESS_PID_REGISTRY_DIR` (default `.harness/pids`), `HARNESS_RUNAWAY_CPU_PCT` (default 50) e `HARNESS_RUNAWAY_MIN_AGE_SECONDS` (default 3600). `HARNESS_REAP_CHROMIUM_MAX_AGE_SECONDS` permanece no schema por compatibilidade, mas idade isolada não autoriza mais kill.

**Checklist universal — construir qualquer guard/checker que funcione de verdade**

A lição por trás do reap-leaks generaliza para qualquer guard novo do harness (Stop, PreToolUse, SessionStart...):

1. **Cobrir o caso REAL, não só o previsto.** Antes de escrever o padrão de detecção, reproduzir o cenário de falha concreto — um guard desenhado só para o caso imaginado na hora do design deixa passar a variação real que ninguém antecipou.
2. **Ligar a um hook determinístico**, nunca a um comando manual ou a uma instrução em prosa (README, CLAUDE.md). Uma salvaguarda que depende de alguém lembrar de rodar não reduz taxa de erro — só vira enforcement quando o harness a dispara sozinho, no evento certo.
3. **Testar que dispara sozinho.** Provocar o cenário de verdade (processo vazado, claim sem prova, diff de UI sem evidência) e confirmar o exit code e o efeito observado — nunca validar só por leitura do script.

## marathon-precompact — o irmão PreCompact

**O que é** — [templates/.harness/hooks/marathon-precompact.sh](../../templates/.harness/hooks/marathon-precompact.sh), registrado em `PreCompact` (dispara quando o contexto da sessão vai ser compactado). Se há maratona ativa, registra a compactação no journal do `RUN.md` — na volta, o `marathon-reinject` (capítulo 02) restaura o estado. O par precompact/reinject é o que faz uma execução longa SOBREVIVER à compactação de contexto.

## O que fica de lição

Os porteiros do Stop são a materialização de "definition of done" como código: prova antes de claim, pixel antes de "UI pronta", checklist antes de parar, faxina antes de sair. Cada um tem escape hatch honesto (reformular o veredito; SKIP com TTL e motivo; `AGUARDANDO:`; anti-prisão de 3 strikes) — gate sem válvula legítima ensina o agente a contornar o gate.
