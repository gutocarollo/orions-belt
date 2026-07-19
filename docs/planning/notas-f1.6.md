# F1.6 — Des-driftar o AGENTS.md: regra do filtro determinístico

Fonte: `/home/augusto/code/learnhouse/.claude/CLAUDE.md` (só leitura, D11). Saída nesta rodada
(F1.6): `templates/{% if use_codex %}AGENTS.md{% endif %}.jinja` (path na raiz de `templates/` com
Jinja-no-nome, pós-restructure F3 — `AGENTS.md` vive na raiz do projeto-alvo, não dentro de um
wrapper `.codex/`; a árvore de `templates/` inteira foi reorganizada nessa rodada, ver `docs/log.md`).
Contexto: `docs/planning/00-plano-consolidado.md` §4 (matriz de paridade instruções: `CLAUDE.md` ↔
`AGENTS.md`) e §6 F1.6.

**Atualização F5 (path mudou, a regra do filtro abaixo não):** `templates/AGENTS.md.jinja` virou
incondicional (gerado independente de `use_codex`) e `templates/{% if use_claude %}.claude{% endif %}/CLAUDE.md.jinja`
passou a existir, incluindo o mesmo arquivo via `{% include %}` do Jinja — bug real encontrado ao
desenhar `harness-init`: Claude Code não lê `AGENTS.md` (sem fallback, confirmado contra docs
oficiais), então `use_claude=true`/`use_codex=false` ficava sem nenhum arquivo de instrução. Ver
commit F5 correspondente para o detalhe.

## Drift encontrado (mais do que o coordenador citou — achado real, não assumido)

O coordenador citou "última sync: 2026-07-06, falta §15/§16" como o drift conhecido. Lendo os
dois arquivos por completo (542 linhas `CLAUDE.md` × 468 linhas `AGENTS.md`) e comparando
heading a heading, o drift real é maior:

| # | Onde | `CLAUDE.md` (atual) | `AGENTS.md` real (drift) |
|---|---|---|---|
| 1 | §6 | "Planejamento e Clarificação com Trade-offs Aplicados" — blocos `D[n]` completos (comportamento/exemplo bom/exemplo ruim/quando escolher), regra "PROIBIDO pergunta seca" | "Clarificação" — versão ANTIGA, "até 5 perguntas diretas e numeradas" |
| 2 | §0 item 0 | "...faça um bloco de decisão/pergunta para cada decisão aberta seguindo a seção 6..." | "...faça até 5 perguntas numeradas e monte o plano sequencial" (consistente com o drift de §6, mesma raiz) |
| 3 | §8 | tem o bullet "Evidência adjacente NÃO é prova" (lição promovida 2026-07-07/08) | bullet ausente |
| 4 | §15 | "Workflow Orchestration (adaptado de Boris Cherny)" — presente | ausente |
| 5 | §16 | "Self-Improvement Loop (lessons.md + hooks)" — presente | ausente |

Achados 1-3 são NOVOS (não citados pelo coordenador) — confirma que o `AGENTS.md` real está mais
desatualizado do que a última auditoria registrou. Prova de cada achado: `docs/planning/notas-f1.6.md`
não repete os greps aqui; ver o relatório da sessão que gerou este doc (comandos reais rodados,
`grep -n`/`diff` linha a linha entre os dois arquivos).

## A regra do filtro (para F4 implementar como script, não decisão ad-hoc)

**Fonte de verdade = `.claude/CLAUDE.md`, não o `AGENTS.md` antigo.** O filtro não tenta
reconciliar/mesclar o `AGENTS.md` desatualizado — ele REGENERA do zero a partir do `CLAUDE.md`
atual, porque `CLAUDE.md` é o documento que efetivamente recebe manutenção (o próprio §16 do
CLAUDE.md descreve o loop capturar→injetar→promover, que só edita CLAUDE.md).

### 1. Bloco excluído (infra/credenciais/URLs de prod)

Delimitação exata: da linha que começa com `## ⭐ PRODUÇÃO` até a linha imediatamente ANTERIOR a
`## 0. LEI ZERO`, inclusive o separador ASCII `-----...-----` que fecha o bloco e a linha em
branco entre ele e `## 0.`. No `CLAUDE.md` atual isso é linhas 136-154 (heading na 137, separador
na 153). Critério de detecção determinístico para o script F4: regex `^## ⭐ PRODUÇÃO` marca
início; o próximo heading `^## \d+\.` marca fim (exclusive). Não é uma lista de termos a redigir
(esse é o job do scanner de segredos, `docs/planning/00-plano-consolidado.md` §7) — é um range de
HEADING, porque todo o bloco de infra vive contíguo sob esse único heading.

**Achado adicional:** 1 menção residual a infra SOBREVIVE fora do bloco removido — §10
(Definition of Done), bullet "Claim sobre prod exige evidência no alvo de prod (state-check da
skill `deploy-qq-academy`)". Não é um segundo bloco de infra (é uma referência de 1 linha dentro
de uma regra de metodologia genérica), então não é excluída — é envolvida em condicional
`{% if has_prod_stack %}` (ver §3 abaixo) e o nome da skill genérico (`deploy-qq-academy` →
"a skill de deploy", já que o nome parametrizado exato dessa skill é escopo de F3 item 3, não
resolvido ainda nesta rodada).

### 2. O que É mantido verbatim

Tudo mais: os 7 blocos `⭐ REFERÊNCIA CANÔNICA` que precedem o bloco de infra (Dropdown, Charts
Bklit, Evidência visual UI, Repo Wiki Karpathy, Understand Anything, DTCG, Codex-native Council)
+ §0 a §16 completos + "File paths for Augusto". **Decisão explícita:** o filtro NÃO tenta separar
"metodologia genérica portável" de "decisão de produto específica do learnhouse" (ex.: Bklit UI
para charts, animação de dropdown com `lh-dropdown-reveal`) — isso é um scope MAIOR (curadoria de
conteúdo) que o pedido não pediu ("mantém o resto"). Filtro = range de exclusão único (o bloco de
infra), não uma triagem semântica de cada bloco restante.

### 3. Substituições `{{ VAR }}` aplicadas (schema `03-hardcodes.md` §3)

| Padrão no `CLAUDE.md` | Substituição | Ocorrências | Variável já existe no schema? |
|---|---|---|---|
| `LearnHouse` (Title-Case, prosa/heading) | `{{ project_name }}` | 2 | sim (`PROJECT_NAME`) |
| `learnhouse` (minúsculo, prosa) | `{{ project_name }}` | 2 | sim |
| `learnhouse-delivery-council` | `{{ project_name }}-delivery-council` | 3 | sim |
| `learnhouse-adversarial-reviewer` | `{{ project_name }}-adversarial-reviewer` | 3 | sim |
| `learnhouse-context-scout` | `{{ project_name }}-context-scout` | 1 | sim |
| `learnhouse-implementer` | `{{ project_name }}-implementer` | 1 | sim |
| `learnhouse-test-auditor` | `{{ project_name }}-test-auditor` | 1 | sim |
| `/home/augusto/code/learnhouse` | `{{ project_root }}` | 1 | sim (`PROJECT_ROOT`) |
| `localhost:5433` (porta do DB dev, §0 item 0) | `localhost:{{ harness_dev_db_port }}` | 1 | sim (`HARNESS_DEV_DB_PORT`) |
| "VSCode Remote-SSH nesta VPS Linux" | generalizado para não citar VPS (não é `{{VAR}}` — é reescrita de frase, já que não é um valor de schema, é uma alegação de ambiente) | 1 | n/a |
| bullet residual `deploy-qq-academy` (§10) | envolvido em `{% if has_prod_stack %}` + nome genérico | 1 | sim (`has_prod_stack` já existe em `copier.yml`) |

**Limitação conhecida e documentada (não fabricada como resolvida):** não existe hoje uma
variável `PROJECT_DISPLAY_NAME` separada de `PROJECT_NAME` (o slug). Renderizando com
`project_name=learnhouse` (minúsculo, forçado pelo `validator` do `copier.yml`), o heading
"REFERÊNCIA CANÔNICA — LearnHouse Codex-native Council" vira "...— learnhouse Codex-native
Council" (minúsculo) em vez de manter o Title-Case. É a ÚNICA diferença encontrada na comparação
heading-a-heading contra o `CLAUDE.md` real (`diff` de 26 vs 25 headings — a diferença de contagem
é só o heading de PRODUÇÃO removido; o `diff` textual das 25 linhas remanescentes mostra
exatamente 1 linha diferente, a de capitalização). Se isso importar visualmente, a correção é
adicionar `project_display_name` ao schema em F3 — não fiz isso agora para não expandir o schema
sem necessidade citada pelo pedido.

### 4. O que NÃO foi tocado (fora de escopo desta rodada, não esquecido)

- Convenções de ferramenta (`.claude/`, `.codex/`, `scripts/`, `docs/`, `tasks/lessons.md`) — regra
  já estabelecida em `03-hardcodes.md` §2.12 ("não parametrizar os dois primeiros além de
  constantes com default fixo"). Path onde os scripts de `engine/lint/`/`engine/contract/` do
  agent-harness efetivamente rodam DENTRO de um projeto-alvo instalado é uma questão de
  arquitetura de distribuição ainda aberta (sinalizada em F0), não resolvida por este filtro.
- Exemplos ilustrativos dentro de blocos canônicos que citam nomes de projeto como comparação
  (ex.: `--qq-green-50..950` no bloco DTCG) — são exemplos concretos de convenção de nomenclatura,
  não valores de identidade a trocar.

## Script determinístico para F4 (pseudocódigo, não implementado ainda)

```
1. ler .claude/CLAUDE.md
2. localizar heading "## ⭐ PRODUÇÃO" (regex ^## ⭐ PRODUÇÃO)
3. localizar o heading seguinte que bate ^## \d+\. (hoje: "## 0. LEI ZERO")
4. remover o range [heading_producao, proximo_heading) inclusive a linha em branco
   imediatamente anterior ao heading removido (evita gap duplo)
5. aplicar tabela de substituição regex (seção 3 acima) — cada entrada é
   (pattern, replacement) fixo, versionado junto com o script
6. envolver bullets residuais de prod-stack fora do range removido em
   {% if has_prod_stack %} ... {% endif %} — lista de bullets residuais
   também versionada (hoje: 1 entrada, §10)
7. prefixar com o cabeçalho de proveniência (bloco {% raw %} explicando a
   regra, para quem ler o .jinja entender que não é edição manual)
8. escrever templates/{% if use_codex %}AGENTS.md{% endif %}.jinja (path pós-restructure F3 —
   raiz de templates/, não dentro de um wrapper .codex/; renomeado para templates/AGENTS.md.jinja,
   incondicional, na rodada F5 — ver nota no topo deste doc)
```

## Gate (rodado nesta sessão — comando + resultado real)

```
python3 -c "... jinja2 ... tmpl.render(project_name='learnhouse', project_root='/home/augusto/code/learnhouse', harness_dev_db_port=5433, has_prod_stack=True)" -> 44959 bytes, 0 placeholders sobrando
grep -c 'srv1777233|qq-academy_|admin@school.dev|kj6gzi' CLAUDE.md      -> 5
grep -c 'srv1777233|qq-academy_|admin@school.dev|kj6gzi' renderizado    -> 0
diff <(grep '^## ' CLAUDE.md | grep -v PRODUÇÃO) <(grep '^## ' renderizado) -> 1 linha diferente (LearnHouse vs learnhouse, capitalização — limitação documentada acima)
grep -c '^## 15\.|^## 16\.' AGENTS.md real  -> 0 (confirma ausência)
grep -c '^## 15\.|^## 16\.' renderizado     -> 2 (confirma presença — des-drift provado)
grep -c 'Evidência adjacente' AGENTS.md real -> 0
grep -c 'Evidência adjacente' renderizado    -> 1
```

**Conclusão do gate:** o renderizado cobre semanticamente 100% do `CLAUDE.md` menos o bloco de
infra (25/25 headings não-infra correspondem, 1 diferença de capitalização documentada) e é
estritamente MAIS completo que o `AGENTS.md` real (tem §15/§16, tem o §6 atual com blocos D[n],
tem a lição promovida do §8 — nenhum desses 3 existe no `AGENTS.md` real hoje).
