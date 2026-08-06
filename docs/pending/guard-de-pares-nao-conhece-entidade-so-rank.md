---
title: O guard de pares coloridos resolve por RANK; a lei exige ENTIDADE na cabeça
status: aberto
quem_resolve: agente
severidade: media
bloqueia: conformidade total do ds-gate com a GRAMMAR do ui-tokenizer-v2
fonte: templates/tests/test_ds_pairs_oklch.sh:86
citacao: --primary-text: oklch(0.62 0.02 250);
updated: 2026-08-06
---

## O que falta

A prosa dos templates já ensina o nome canônico — `<entidade>.<rank>.background-color` +
`<entidade>.<rank>.text`, com entidade na cabeça. Os **guards** ainda resolvem por rank puro:
`PAIRS` é uma lista de ranks (`primary`, `destructive`, `success`, `info`, `premium`) e o par é
construído por concatenação em `pair_text()`. A fixture citada no frontmatter é a prova mais curta:
o caso `1b` do teste declara `--primary-text` — rank puro, sem entidade — e o guard resolve.

> Nota de ancoragem: o `fonte:` aponta para o TESTE e não para o guard porque o nome do arquivo do
> guard carrega jinja (`{% if use_ds_gate %}...{% endif %}`) e o `ref_integrity` reprova o link
> gerado no índice — ele barrou o primeiro commit desta pendência.

## Por que isso é divergência, e não descuido

`docs/law/GRAMMAR.md` §5.5 do `ui-tokenizer-v2` (verdade absoluta do vocabulário) diz:

> *"The head must be a REAL entity you can point at on screen. Still forbidden as a head: **a rank
> (`primary`)**, a whitelabel (`content`/`surface`/`semantic`), an architectural tier, a raw pigment
> (`pink`)."*

E o template canônico (`docs/law/design_system_template.json`) nomeia o par exatamente assim:

```
button.primary.background-color     ← preenchimento
button.primary.text                 ← o que fica sobre ele
```

As 39 entidades legais estão nele: `attachment, avatar, badge, banner, button, card, chart,
chat-message, checkbox, code-block, data-table, divider, drawer, empty-state, field, focus-ring,
list-row, logo, markdown, menu, modal, nav-item, overlay, page, pill, popover, progress, prompt,
radio, search, select, sidebar, skeleton, slider, stat, toast, toggle, toolbar, tooltip`.

## Por que NÃO foi corrigido junto

O guard é consumidor de **SOURCE**: ele lê o `globals.css` de um projeto que ainda não migrou. Hoje
esse arquivo, num projeto shadcn, declara `--primary-foreground` — rank puro, sem entidade. Ensinar
o guard a exigir entidade sem que o projeto tenha migrado transforma todo par existente em `SKIP`
(inresolvível), que é **falso verde** — pior que o nome errado, porque o gate para de reprovar.

Resolver de verdade exige o inventário de entidades do projeto medido, que é justamente o que o
pipeline do `ui-tokenizer-v2` produz e o guard genérico do orions-belt não tem.

## Como resolver quando for retomado

1. O guard passa a aceitar `--<entidade>-<rank>-text` além das duas formas atuais, com a lista de
   entidades vinda de config (`HARNESS_DS_ENTITIES`) em vez de hardcode.
2. Sem a config, mantém o comportamento atual — projeto não migrado continua sendo checado.
3. Com a config, um par declarado por rank puro deixa de ser só resolvido e passa a ser **reportado**
   como nome legado, dando ao projeto o sinal de migração que hoje não existe.

## O que já foi feito neste ciclo

`pair_text()` resolve `X-text` primeiro e cai em `X-foreground`; `ds-pair-eval.py` ganhou as 25
entradas canônicas `-text` ao lado das 25 legadas; `test_ds_pairs_oklch.sh` ganhou o caso `1b`
provando que o nome canônico resolve e ainda reprova baixo contraste.
