#!/usr/bin/env python3
"""pending_index — o backlog do repositorio vira ARTEFATO, nao memoria de sessao.

POR QUE ESTE SCRIPT EXISTE (2026-08-01). O dono perguntou "o que falta para o
graph loop rodar end-to-end?" e a resposta so pode ser produzida re-derivando
tudo na mao: abrir os 4 planos, o ESTADO.md, os docstrings dos scripts, rodar o
loop, e reconstruir a lista. Isso ja tinha sido feito em sessoes anteriores. Ao
perguntar "nao existe uma pasta de pending? o wiki nao esta indexando as docs e
criando esses checklists?", ele nomeou o defeito: `docs/SCHEMA.md` §3 classifica
o DOCUMENTO (`status: canon|active|superseded|historico|proposta`) e nunca o
ITEM. Um doc `active` pode carregar vinte pendencias e a constituicao nao tem
vocabulario para nenhuma delas. `docs_wiki_lint.py` so VALIDA (orfao, naming,
referencia); nao existia nada que COLHESSE.

Consequencia medida: as pendencias moravam em prosa espalhada por
`docs/plans/*.md` e num `docs/ESTADO.md` escrito a mao — que ja nascia stale,
porque nada o obrigava a acompanhar o codigo.

O CONTRATO. Cada pendencia e UM arquivo em `docs/pending/<id>.md` com
frontmatter. O arquivo existe enquanto o item existe; resolver e DELETAR (o git
guarda o historico — `docs/SCHEMA.md` §"git e o arquivo"). Este script le a
pasta, gera `docs/pending/index.md` e, com `--check`, falha quando o indice
esta velho ou quando o ponteiro para a fonte apodreceu.

A CHECAGEM QUE JUSTIFICA O SCRIPT e a de ponteiro podre. Um backlog cheio de
item ja resolvido e PIOR que backlog nenhum: ele faz o agente perguntar ao dono
uma decisao que a lei ja tomou — foi exatamente o que aconteceu em 2026-07-31
com a D1 de "propriedade no nome", cuja resposta ja estava em GRAMMAR.md nas
Linhas 31, 75 e 289. Por isso todo item declara `fonte: <path>:<linha>` e
`citacao:`, e este script confere que a citacao ainda esta la. Quando a fonte
muda, o item e sinalizado para re-auditoria em vez de continuar sendo afirmado.

Sem dependencia externa (stdlib), como todo guard deste diretorio: o parser de
frontmatter abaixo cobre `chave: valor` plano, que e a forma que o contrato usa.

Uso:
  python3 .harness/lib/pending_index.py            # regenera docs/pending/index.md
  python3 .harness/lib/pending_index.py --check    # nao escreve; falha se stale/podre
  python3 .harness/lib/pending_index.py --json     # o backlog como dado
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # .harness/lib/

from _tooling_conf import get_config, project_root  # noqa: E402

ROOT = project_root()
DOCS = ROOT / get_config("HARNESS_DOCS_DIR", "docs")
PENDING = DOCS / "pending"
INDEX = PENDING / "index.md"

# Chaves obrigatorias. `fonte`/`citacao` sao o que torna o item AUDITAVEL — sem
# elas o backlog vira lista de desejos e ninguem consegue conferir se ja fechou.
REQUERIDAS = ("title", "status", "quem_resolve", "severidade", "bloqueia", "fonte", "citacao", "updated")

STATUS_OK = ("aberto", "bloqueado")
QUEM_OK = ("dono", "agente")
SEVERIDADE_OK = ("bloqueante", "alta", "media", "baixa")
ORDEM_SEVERIDADE = {s: i for i, s in enumerate(SEVERIDADE_OK)}

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FONTE_RE = re.compile(r"^(?P<path>[^:]+?)(?::(?P<line>\d+))?$")

CABECALHO = (
    "<!-- GERADO por .harness/lib/pending_index.py — NAO EDITE A MAO.\n"
    "     A fonte de cada item e o arquivo docs/pending/<id>.md correspondente.\n"
    "     Regenere com: python3 .harness/lib/pending_index.py -->\n"
)

# Tolerancia de deriva do ponteiro: a citacao pode ter andado algumas linhas
# porque alguem inseriu texto acima dela. Isso NAO e apodrecimento — o item
# continua valido. Some da linha declarada e o item vai para re-auditoria.
JANELA = 4


def ler_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parser de frontmatter plano. Devolve (campos, erros)."""
    erros: list[str] = []
    texto = path.read_text(encoding="utf-8")
    if not texto.startswith("---\n"):
        return {}, [f"{path.name}: sem frontmatter"]
    fim = texto.find("\n---\n", 4)
    if fim == -1:
        return {}, [f"{path.name}: frontmatter nao fechado"]
    campos: dict[str, str] = {}
    for linha in texto[4:fim].splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        chave, sep, valor = linha.partition(":")
        if not sep:
            continue
        campos[chave.strip()] = valor.strip().strip("\"'")
    return campos, erros


def corpo(path: Path) -> str:
    texto = path.read_text(encoding="utf-8")
    fim = texto.find("\n---\n", 4)
    return texto[fim + 5 :].strip() if fim != -1 else texto.strip()


def checar_fonte(campos: dict[str, str], nome: str) -> list[str]:
    """O ponteiro para a fonte ainda aponta para o que o item diz que aponta?"""
    problemas: list[str] = []
    bruto = campos.get("fonte", "").strip()
    citacao = campos.get("citacao", "").strip()
    if not bruto:
        return problemas
    m = FONTE_RE.match(bruto)
    if not m:
        return [f"{nome}: fonte fora do formato <path>[:<linha>] -> {bruto!r}"]
    alvo = ROOT / m.group("path")
    if not alvo.is_file():
        return [f"{nome}: fonte inexistente -> {m.group('path')}"]
    if not citacao:
        return problemas
    try:
        linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"{nome}: fonte ilegivel -> {exc}"]

    agulha = " ".join(citacao.split())
    achou_em = [i + 1 for i, l in enumerate(linhas) if agulha in " ".join(l.split())]
    if not achou_em:
        return [
            f"{nome}: PONTEIRO PODRE — a citacao nao existe mais em {m.group('path')}. "
            f"O item pode ja estar resolvido; re-audite antes de afirma-lo."
        ]
    declarada = m.group("line")
    if declarada:
        n = int(declarada)
        if not any(abs(a - n) <= JANELA for a in achou_em):
            problemas.append(
                f"{nome}: fonte com linha desatualizada — declara :{n}, a citacao esta em "
                f"{', '.join(str(a) for a in achou_em[:3])}"
            )
    return problemas


def coletar() -> tuple[list[dict], list[str]]:
    itens: list[dict] = []
    erros: list[str] = []
    if not PENDING.is_dir():
        # Pasta ausente NAO e erro: e um projeto que ainda nao adotou a convencao.
        # Guard que reprova quem nao usa a feature vira ruido e acaba desligado.
        # (Descoberto exercitando este script no proprio orions-belt, 2026-08-01.)
        return itens, []

    vistos: set[str] = set()
    for path in sorted(PENDING.glob("*.md")):
        if path.name in {"index.md", "README.md"}:
            continue
        ident = path.stem
        nome = path.name
        if not ID_RE.match(ident):
            erros.append(f"{nome}: nome fora de kebab-case")
        if ident in vistos:
            erros.append(f"{nome}: id duplicado")
        vistos.add(ident)

        campos, e = ler_frontmatter(path)
        erros.extend(e)
        if not campos:
            continue
        for chave in REQUERIDAS:
            if not campos.get(chave):
                erros.append(f"{nome}: falta a chave obrigatoria {chave!r}")
        if campos.get("status") and campos["status"] not in STATUS_OK:
            erros.append(f"{nome}: status {campos['status']!r} fora de {STATUS_OK}")
        if campos.get("quem_resolve") and campos["quem_resolve"] not in QUEM_OK:
            erros.append(f"{nome}: quem_resolve {campos['quem_resolve']!r} fora de {QUEM_OK}")
        if campos.get("severidade") and campos["severidade"] not in SEVERIDADE_OK:
            erros.append(f"{nome}: severidade {campos['severidade']!r} fora de {SEVERIDADE_OK}")
        if campos.get("updated") and not DATE_RE.match(campos["updated"]):
            erros.append(f"{nome}: updated fora de YYYY-MM-DD -> {campos['updated']!r}")
        erros.extend(checar_fonte(campos, nome))

        itens.append({"id": ident, "arquivo": path.name, **campos})

    itens.sort(
        key=lambda i: (
            0 if i.get("quem_resolve") == "dono" else 1,
            ORDEM_SEVERIDADE.get(i.get("severidade", "baixa"), 9),
            i["id"],
        )
    )
    return itens, erros


def render(itens: list[dict]) -> str:
    dono = [i for i in itens if i.get("quem_resolve") == "dono"]
    agente = [i for i in itens if i.get("quem_resolve") != "dono"]

    L: list[str] = [CABECALHO, "# Pendencias abertas", ""]
    L.append(
        f"**{len(itens)} itens abertos** — {len(dono)} esperam decisao do dono, "
        f"{len(agente)} sao trabalho de agente. Resolver um item e **apagar o arquivo** "
        f"`docs/pending/<id>.md` e regenerar este indice; o git guarda o historico."
    )
    L.append("")
    L.append(
        "Cada item declara a `fonte` que o originou e a `citacao` textual dela. "
        "`pending_index.py --check` confere que a citacao ainda existe — item cujo "
        "ponteiro apodreceu vira **re-auditoria**, nunca afirmacao."
    )
    L.append("")

    for titulo, grupo, nota in (
        ("Espera o dono", dono, "decisao humana: preferencia, escopo, emenda de lei, custo."),
        ("Trabalho de agente", agente, "resolvivel com codigo, medicao ou leitura — nao pergunte, faca."),
    ):
        L.append(f"## {titulo}")
        L.append("")
        if not grupo:
            L.append("Nada aberto.")
            L.append("")
            continue
        L.append(f"_{nota}_")
        L.append("")
        L.append("| | item | severidade | bloqueia | fonte |")
        L.append("|---|---|---|---|---|")
        for i in grupo:
            fonte = i.get("fonte", "")
            path_only = fonte.split(":")[0]
            L.append(
                f"| [ ] | [{i.get('title', i['id'])}]({i['arquivo']}) "
                f"| {i.get('severidade', '?')} | {i.get('bloqueia', '?')} "
                f"| [`{fonte}`](../../{path_only}) |"
            )
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="nao escreve; falha se stale ou podre")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    itens, erros = coletar()

    if args.json:
        print(json.dumps({"itens": itens, "erros": erros}, ensure_ascii=False, indent=1))
        return 1 if erros else 0

    novo = render(itens)
    atual = INDEX.read_text(encoding="utf-8") if INDEX.is_file() else None

    # Projeto que ainda nao adotou a convencao: sem pasta E sem indice, nao ha
    # nada para comparar. Sem esta saida, `--check` cobraria de todo instalado
    # um indice vazio que ninguem pediu — e o guard seria desligado no primeiro
    # dia por ser ruido.
    if not PENDING.is_dir() and atual is None:
        if args.check:
            print("pending-index: OK — docs/pending/ nao existe (convencao nao adotada aqui)")
            return 0
        print(f"pending-index: docs/pending/ nao existe. Crie o primeiro item e rode de novo — contrato em docs/SCHEMA.md §3.1")
        return 0

    if args.check:
        if atual != novo:
            erros.append(
                "docs/pending/index.md esta DESATUALIZADO em relacao aos arquivos da pasta "
                "— rode `python3 .harness/lib/pending_index.py`"
            )
        if erros:
            print("pending-index: FAIL")
            for e in erros:
                print(f"- {e}")
            return 1
        print(f"pending-index: OK — {len(itens)} itens abertos, indice em dia, fontes vivas")
        return 0

    if erros:
        print("pending-index: FAIL (indice NAO regenerado enquanto houver erro)")
        for e in erros:
            print(f"- {e}")
        return 1

    PENDING.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(novo, encoding="utf-8")
    dono = sum(1 for i in itens if i.get("quem_resolve") == "dono")
    print(f"pending-index: escrito {INDEX.relative_to(ROOT)} — {len(itens)} itens ({dono} para o dono)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
