# 08. Execuções longas — marathon, estado durável e o loop de manutenção

Uma execução longa (plano multi-fase, migração em ondas, "termine tudo") tem dois inimigos: a **compactação de contexto** (o runtime resume a conversa e o agente esquece onde estava) e a **parada prematura** (o agente declara o turno encerrado com metade do checklist aberto). O subsistema **marathon** resolve os dois com um princípio: o estado da execução vive em ARQUIVO durável, não no contexto da conversa.

## A anatomia: ACTIVE + RUN.md

Tudo vive sob `HARNESS_RUNS_DIR` (default `.harness/runs`):

- **`ACTIVE`** — arquivo de 1 linha com o slug da maratona em andamento. Existe = há maratona ativa; `rm` nele = encerra.
- **`<slug>/RUN.md`** — o estado durável: objetivo, checklist (`- [ ]` / `- [x]`), a seção **"Próxima ação"** (a instrução exata do que fazer a seguir — é o que o agente executa ao retomar, sem re-planejar) e um journal de eventos.

O contrato de escrita é da skill `marathon` ([template](<../../templates/{% if use_claude %}.claude{% endif %}/skills/marathon/SKILL.md.jinja>)): invocada quando a tarefa é estimada longa (mais de ~1h ou 3+ fases) ou quando `ACTIVE` já existe ao abrir a sessão. O ciclo por item: fechar o item → marcar `[x]` → atualizar "Próxima ação" → seguir.

## Os três hooks que o sustentam

O subsistema é sustentado por três hooks já registrados (capítulos 02 e 06), que fecham o ciclo de vida:

| Momento | Hook | Papel |
|---|---|---|
| Contexto vai compactar | [marathon-precompact.sh](../../templates/.harness/hooks/marathon-precompact.sh) (`PreCompact`) | Registra a compactação no journal do RUN.md — o estado já está em disco, o hook só marca o evento |
| Sessão reabre (`compact`/`resume`) | [marathon-reinject.sh](../../templates/.harness/hooks/marathon-reinject.sh) (`SessionStart`) | Reinjeta as primeiras 150 linhas do RUN.md no contexto: "execute a Próxima ação, não re-planeje" |
| Agente tenta parar | [marathon-stop-gate.sh](../../templates/.harness/hooks/marathon-stop-gate.sh) (`Stop`) | Bloqueia a parada com itens abertos, devolvendo a "Próxima ação"; anti-prisão de 3 strikes sem progresso |

```mermaid
flowchart TD
    A["tarefa longa comeca: skill marathon cria runs/slug/RUN.md + ACTIVE"] --> B["agente executa item a item: fecha, marca x, atualiza Proxima acao"]
    B --> C{"contexto compacta no meio?"}
    C -- "sim" --> D["PreCompact marca no journal"]
    D --> E["sessao reabre: marathon-reinject injeta o RUN.md"]
    E --> B
    C -- "nao" --> F{"agente tenta encerrar o turno"}
    F --> G{"checklist com itens abertos?"}
    G -- "nao" --> H["parada legitima"]
    G -- "sim" --> I{"Proxima acao = AGUARDANDO: decisao do usuario?"}
    I -- "sim" --> H
    I -- "nao" --> J["stop-gate bloqueia e devolve a Proxima acao"]
    J --> B
    J -. "3 bloqueios sem o RUN.md mudar" .-> K["anti-prisao: libera com aviso; maratona segue ATIVA"]
```

As paradas legítimas são explícitas: checklist zerado, ou "Próxima ação" começando com `AGUARDANDO: <pergunta>` (bloqueado em decisão humana). O anti-prisão usa o mtime do RUN.md como detector de progresso: bloqueios consecutivos sem o arquivo mudar até o limite `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS` (default 3) liberam com aviso — cobrar progresso, não manter refém.

## Como configurar

- `HARNESS_RUNS_DIR` — onde o estado durável vive (default `.harness/runs`), lido pelos três hooks. O mesmo diretório abriga os slots do semáforo de subagents (capítulo 04) e o ledger do council (capítulo 11, `HARNESS_LEDGER_DIR` deriva dele).
- `HARNESS_MARATHON_MAX_BLOCKS_WITHOUT_PROGRESS` — o limite do anti-prisão (default 3), lido pelo stop-gate em runtime.

## O loop de manutenção

As instruções de projeto geradas ([templates/AGENTS.md.jinja](../../templates/AGENTS.md.jinja)) referenciam um segundo padrão de execução recorrente: o **loop de manutenção** — uma passada periódica que roda os lints da wiki (capítulo 10), verifica lições pendentes de promoção (capítulo 12), aponta árvore git suja e (se instalados) os módulos condicionais de className/design-system. A convenção: um arquivo `.claude/loop.md` descreve os checks da passada, e o runtime que suportar comando de loop recorrente (`/loop` no Claude Code) o executa em intervalo.

**Materializado desde R5** (plano de resgate §2): [templates/{% if use_claude %}.claude{% endif %}/loop.md.jinja](<../../templates/{% if use_claude %}.claude{% endif %}/loop.md.jinja>) — instalado sempre que `use_claude=true` (não tem flag própria; Codex não tem comando de loop nativo, capítulo 15 item 1). Os checks apontam só para motores que este projeto de fato instalou: `docs_wiki_lint.py`/`ref_integrity.py` de `.harness/lib/` sempre; o check de mining de className é condicional a `use_ui_skills`; o check de ratchet de design-system é condicional a `use_ds_gate`; o check de **frescor do grafo** (conta os arquivos mudados sob o `PROJECT_ROOT` do Understand Anything desde o último build via `meta.json` + diff relativo, e dispara `/understand` incremental quando passam de `HARNESS_GRAPH_REFRESH_THRESHOLD`, default 15) é condicional a `harness_understand_apps_root`. O threshold existe porque `/understand` é LLM-heavy (subagents, cota da assinatura) — o loop paga o grafo só quando o diff acumulado justifica, não a cada passada. Se o seu runtime não tem loop nativo (ou `use_claude=false`), o equivalente é um cron chamando o agente em modo não-interativo com o mesmo checklist — os componentes que a passada roda (lints, lessons, gates) são todos instalados e funcionam standalone independente do arquivo de orquestração existir.

**A tolerância a imperfeição é deliberada.** O check de wiki (`docs_wiki_lint.py`, capítulo 10) devolve dois níveis de severidade e a passada trata cada um diferente: **FAIL** — por exemplo, um arquivo sob `docs/` sem menção em índice algum — é o que a passada corrige de fato, editando o índice da categoria e re-rodando o lint até ficar verde; **WARN** — naming fora do padrão kebab-case, ou um índice vivo linkando a uma pasta de arquivo morto como wayfinding intencional — não bloqueia a passada, fica registrado como backlog que o próprio loop vai "queimando" aos poucos em passadas futuras. A razão é econômica: forçar a migração completa de naming numa única passada não é "barato o suficiente" para caber na regra de abertura da seção ("consertando o que for barato e reportando o que não for") — então o lint deixa a porta aberta para ignorar o cosmético sem deixar de bloquear o que de fato quebra a navegabilidade da wiki. Detalhe completo dos dois níveis no capítulo 10.

### O comando /loop e o modo self-paced (ScheduleWakeup)

**O que é** — `/loop` é o motor genérico de repetição do runtime: um slash command (atalho iniciado por barra que injeta uma instrução pronta na conversa) que faz o agente executar um prompt — ou outro slash command — repetidamente, sem que alguém precise pedir de novo a cada passada. Ele aceita dois modos:

- **Intervalo fixo** (`/loop 5m /algum-comando`) — funciona como um cronômetro de cozinha: a cada 5 minutos dispara, e o agente roda o comando de novo, sem julgamento sobre se ainda faz sentido continuar.
- **Self-paced** (`/loop` sozinho, ou `/loop <prompt>` sem intervalo) — quem decide **quando** volta a rodar é o próprio agente, programando um **ScheduleWakeup** ("agendar despertar"). A analogia útil: é um despertador que o próprio agente configura antes de "dormir" entre passadas. Se avaliou que nada urgente está acontecendo, marca o despertador para mais tarde; se a situação pede atenção, marca para mais cedo; se concluiu que não há mais razão para voltar, simplesmente **não programa o despertador** — e o loop morre de morte natural.

Esse último ramo é o que separa um loop bem projetado de um processo zumbi: a condição de parada precisa ser explícita, escrita no próprio prompt que o loop executa. **Loop sem condição de parada não é automação — é vazamento**: cada passada sem critério de término consome ciclo de agente, tokens e, se a passada tocar rede ou disco, recursos externos, indefinidamente, sem que ninguém tenha decidido que aquilo deveria continuar. O `loop.md` de manutenção e qualquer loop de propósito específico que um projeto construa sobre o mesmo motor (por exemplo, uma skill que acompanha um processo externo de longa duração — um deploy em andamento, uma importação de dados — até ele terminar) só são seguros porque escrevem a condição de parada em texto, nunca a deixam implícita.

```mermaid
flowchart TD
    A["Alguem digita /loop"] --> B{"Intervalo informado?"}
    B -->|"sim, ex 5m"| C["Roda o prompt a cada intervalo fixo, como cronometro"]
    B -->|"nao"| D["Modo self-paced"]
    D --> E["Executa uma passada do prompt"]
    E --> F{"Ainda ha motivo para continuar?"}
    F -->|"sim"| G["Programa o proprio despertador: ScheduleWakeup"]
    G --> H["Fica disponivel ate o horario marcado, sem bloquear quem esta usando"]
    H --> E
    F -->|"nao"| I["Nao agenda proxima passada: o loop encerra sozinho"]
```

Convenção deste framework: `/loop` **sem argumentos** roda a passada de manutenção descrita em `.claude/loop.md`. Um projeto também pode escrever um prompt próprio e invocar o mesmo motor em modo self-paced dentro de uma skill de propósito específico, calibrando o próprio `ScheduleWakeup` conforme o sinal que recebe a cada ciclo — por exemplo, se a fonte externa que o ciclo consulta responder com erro de rate limit, aumentar o intervalo no próximo agendamento em vez de insistir no mesmo cadence.

### As 3 regras de um loop autônomo seguro

Qualquer passada de loop autônomo — a de manutenção deste framework ou uma escrita por cima do mesmo motor — segue 3 regras fixas, já embutidas no template real ([loop.md.jinja](<../../templates/{% if use_claude %}.claude{% endif %}/loop.md.jinja>), seção "Regras do loop"):

1. **Ação irreversível fica FORA do loop.** Push, delete de arquivo tracked, deploy, qualquer mutação em produção: a passada só REPORTA, nunca executa. Um loop que corre sozinho, sem supervisão humana em tempo real a cada ciclo, não pode ter no escopo nenhuma ação que não dê para desfazer se o julgamento daquela passada estiver errado.
2. **Cada passada termina com um resumo curto e limitado** (3-6 linhas no template): o que passou, o que foi consertado, o que precisa de decisão humana. Um loop que roda sem ninguém acompanhando cada ciclo não pode produzir um relatório do tamanho da tarefa inteira a cada volta — o resumo precisa caber no que alguém lê de relance ao voltar a prestar atenção.
3. **Auto-término após passadas vazias.** Nada a fazer em 2 passadas seguidas → encerrar o loop (em modo self-paced: não agendar a próxima). É a mesma lógica do "não programar o despertador" da subseção anterior, só que como regra explícita de desligamento: uma ronda de manutenção que passa duas vezes seguidas sem achar nada para consertar não tem motivo para continuar rondando período após período — ela para e só volta a ser chamada sob demanda.

**Exemplo (cenário simulado)** — num projeto `demo-app`, alguém dispara `/loop` sem argumentos numa manhã tranquila. Passada 1: todos os checks de `.claude/loop.md` passam verdes; o agente reporta o resumo e agenda um `ScheduleWakeup`. Passada 2: tudo verde de novo. Pela regra 3, o agente **não** agenda a terceira passada e encerra o loop, declarando o motivo no próprio resumo. Nenhum processo fica rodando à toa.

## O que fica de lição

Contexto de conversa é memória volátil; arquivo é memória durável. Qualquer execução que não caiba com folga numa janela de contexto precisa externalizar o estado — e uma vez externalizado, os hooks garantem as três pontas: preservar (precompact), restaurar (reinject) e não abandonar (stop-gate).
