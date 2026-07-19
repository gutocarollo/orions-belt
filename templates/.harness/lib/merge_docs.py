#!/usr/bin/env python3
"""merge_docs.py — merge ADITIVO (nunca overwrite) para superfícies LOCAIS do
projeto-alvo (F5, docs/planning/00-plano-consolidado.md §5).

Lição real que motivou esta regra (capturada no lessons.md do harness-doador
de referência): um `mv` que sobrescreveu
um arquivo canônico sem checar se já existia. Este módulo garante que
CLAUDE.md/AGENTS.md preexistentes NUNCA são substituídos inteiros, e que
settings.json preexistente tem os hooks do harness UNIDOS (não sobrepostos)
aos hooks que o usuário já tinha.

Três estratégias, por tipo de arquivo (B3, revisão adversarial pós-v1.0.0: os
4 arquivos "sensíveis" do fluxo brownfield são AGENTS.md, .claude/CLAUDE.md,
.claude/settings.json e .gitignore — os 3 primeiros usam as 2 estratégias
abaixo, .gitignore usa a 3ª):

  - Markdown (CLAUDE.md/AGENTS.md): bloco marcado
    `<!-- harness-wiki:begin (vX) -->` ... `<!-- harness-wiki:end -->`.
    Primeira instalação: bloco é ANEXADO ao fim do arquivo existente (o
    conteúdo do usuário antes do bloco nunca é tocado). Reinstalação/update:
    o CONTEÚDO DENTRO do bloco marcado é substituído (idempotente — não
    duplica o bloco a cada rodada), o resto do arquivo continua intocado.

  - JSON (settings.json): merge estrutural por chave de evento de hook —
    reconciliação por OWNERSHIP (A4, gap real: dedup por `command` sozinho
    não bastava — mudança de matcher/timeout no MESMO hook nunca chegava,
    hook removido upstream persistia, rename deixava as duas entradas
    registradas). Toda entrada cujo `command` aponta para `.harness/hooks/`
    é OWNED pelo harness: o lado NOVO (do template renderizado agora) é
    sempre a fonte de verdade para o conjunto OWNED — update, remoção e
    rename são resolvidos numa reconciliação completa a cada rodada. Toda
    entrada cujo `command` NÃO aponta para `.harness/hooks/` é EXTERNA
    (hook do próprio usuário) e é SEMPRE preservada. Chaves fora de `hooks`
    (permissions, env, model, etc.) do arquivo existente são preservadas
    verbatim.

  - .gitignore: mesmo mecanismo de bloco marcado do Markdown, mas com
    comentário `#` (não `<!-- -->`, que numa linha de .gitignore não é
    comentário — vira um padrão de ignore literal começando com `<`).

CLI:
  merge_docs.py markdown --existing PATH --new PATH [--label TEXT]
      -> escreve PATH com o merge aplicado (idempotente); imprime JSON
         {"action": "created"|"appended"|"updated-block", "path": ...}
  merge_docs.py settings-json --existing PATH --new PATH
      -> escreve PATH com o merge aplicado; imprime JSON
         {"action": "created"|"merged", "path": ..., "hooks_added": N,
          "hooks_kept": N, "hooks_removed_stale_owned": N}
  merge_docs.py gitignore --existing PATH --new PATH [--label TEXT]
      -> escreve PATH com o merge aplicado (idempotente); imprime JSON
         {"action": "created"|"appended"|"updated-block", "path": ...}

Fail-open: se `--existing` não existir, o comportamento é "criar do zero"
(copia `--new` verbatim) — não é um erro.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# NOME DO MARCADOR (G7, revisão adversarial pós-v1.0.0): renomeado para
# `harness-wiki:begin/end` para acompanhar o rename do produto (ver README.md
# raiz — o nome anterior do repo/produto virou histórico em docs/planning/);
# o marcador antigo só existia até aqui em código/teste do PRÓPRIO framework,
# nunca em nenhum projeto-alvo real (produto ainda não publicado) — renomear
# não quebra idempotência de update de ninguém. Se este marcador algum dia
# tiver sido escrito num projeto-alvo com o nome antigo antes desta rodada,
# `merge_markdown` cai no ramo "sem bloco marcado ainda" (BEGIN_RE não casa)
# e ANEXA um novo bloco em vez de atualizar o antigo in-place — não perde
# conteúdo, mas duplica o bloco uma vez; documentado aqui por transparência.
BEGIN_RE = re.compile(r"<!-- harness-wiki:begin.*?-->", re.S)
END_MARK = "<!-- harness-wiki:end -->"


def _marker_block(new_content: str, label: str) -> str:
    return (
        f"<!-- harness-wiki:begin ({label}) — gerado por harness-wiki; "
        f"conteúdo entre os marcadores é reescrito em cada `harness-init`/`copier update`, "
        f"NUNCA edite dentro deste bloco (a próxima rodada sobrescreve). "
        f"Conteúdo ACIMA do bloco é do projeto e nunca é tocado. -->\n"
        f"{new_content.rstrip()}\n"
        f"{END_MARK}\n"
    )


def merge_markdown(existing_path: Path, new_path: Path, label: str) -> dict:
    new_content = new_path.read_text(encoding="utf-8")

    if not existing_path.exists():
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_path.write_text(_marker_block(new_content, label), encoding="utf-8")
        return {"action": "created", "path": str(existing_path)}

    existing_text = existing_path.read_text(encoding="utf-8")
    begin_match = BEGIN_RE.search(existing_text)
    end_idx = existing_text.find(END_MARK)

    if begin_match and end_idx != -1 and end_idx > begin_match.start():
        before = existing_text[: begin_match.start()]
        after = existing_text[end_idx + len(END_MARK):]
        merged = before.rstrip() + "\n\n" + _marker_block(new_content, label) + after.lstrip("\n")
        existing_path.write_text(merged, encoding="utf-8")
        return {"action": "updated-block", "path": str(existing_path)}

    # sem bloco marcado ainda -> ANEXA ao fim, nunca sobrescreve o que já existe.
    merged = existing_text.rstrip() + "\n\n" + _marker_block(new_content, label)
    existing_path.write_text(merged, encoding="utf-8")
    return {"action": "appended", "path": str(existing_path)}


# --- .gitignore (B3, 4º arquivo sensível — mesma mecânica de bloco marcado do
# Markdown, mas com comentário `#` em vez de `<!-- -->` porque .gitignore não
# é HTML/Markdown e um comentário `<!-- -->` cru viraria um PADRÃO de ignore
# literal (uma linha começando com `<` não é comentário em .gitignore — só
# linhas começando com `#` são). ---
GITIGNORE_BEGIN_RE = re.compile(r"^# harness-wiki:begin.*$", re.M)
GITIGNORE_END_MARK = "# harness-wiki:end"


def _gitignore_block(new_content: str, label: str) -> str:
    body = new_content.rstrip("\n")
    return (
        f"# harness-wiki:begin ({label}) — gerado por harness-wiki; conteúdo entre\n"
        f"# os marcadores é reescrito em cada harness-install/copier update, NÃO edite\n"
        f"# dentro deste bloco. Linhas ACIMA do bloco são do projeto e nunca são tocadas.\n"
        f"{body}\n"
        f"{GITIGNORE_END_MARK}\n"
    )


def merge_gitignore(existing_path: Path, new_path: Path, label: str) -> dict:
    new_content = new_path.read_text(encoding="utf-8")

    if not existing_path.exists():
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_path.write_text(_gitignore_block(new_content, label), encoding="utf-8")
        return {"action": "created", "path": str(existing_path)}

    existing_text = existing_path.read_text(encoding="utf-8")
    begin_match = GITIGNORE_BEGIN_RE.search(existing_text)
    end_idx = existing_text.find(GITIGNORE_END_MARK)

    if begin_match and end_idx != -1 and end_idx > begin_match.start():
        before = existing_text[: begin_match.start()]
        after = existing_text[end_idx + len(GITIGNORE_END_MARK):]
        merged = before.rstrip("\n") + "\n\n" + _gitignore_block(new_content, label) + after.lstrip("\n")
        existing_path.write_text(merged, encoding="utf-8")
        return {"action": "updated-block", "path": str(existing_path)}

    # sem bloco marcado ainda -> ANEXA ao fim, nunca sobrescreve o que já existe.
    merged = existing_text.rstrip("\n") + "\n\n" + _gitignore_block(new_content, label)
    existing_path.write_text(merged, encoding="utf-8")
    return {"action": "appended", "path": str(existing_path)}


def _hook_command(entry: dict) -> str | None:
    return entry.get("command")


# A4 (revisão adversarial pós-v1.0.0, gap real): a versão anterior deduplicava
# só por string de `command` e SEMPRE preservava o hook antigo — 3 consequências
# ruins: (1) mudança upstream de matcher/timeout/statusMessage do MESMO hook
# nunca chegava (o command idêntico contava como "já registrado", a entrada
# antiga ficava congelada); (2) hook removido no template novo (upstream
# decidiu descontinuar) persistia para sempre no projeto-alvo; (3) rename de
# script (ex.: `foo.sh` -> `foo-v2.sh`) deixava as DUAS entradas registradas
# (double-fire — o hook antigo nunca é removido porque seu command não bate
# com o novo).
#
# Fix: reconciliação por OWNERSHIP, não por igualdade de string. Todo hook do
# harness roda um script sob `.harness/hooks/` (fonte única, ver
# `templates/{% if use_claude %}.claude{% endif %}/settings.json.jinja` — cada
# `command` é sempre `bash/python3 "$CLAUDE_PROJECT_DIR/.harness/hooks/<script>"`).
# Esse path é o sinal de "hook OWNED pelo harness". Numa reconciliação:
#   - toda entrada EXISTENTE cujo command bate no padrão OWNED é DESCARTADA
#     (o lado novo, vindo do template renderizado agora, é a fonte de verdade
#     para tudo que o harness possui — reconcilia update, remoção E rename).
#   - toda entrada EXISTENTE cujo command NÃO bate (hook do próprio usuário,
#     ex. `npm run lint-staged`, hook custom dele) é SEMPRE preservada.
#   - todas as entradas do lado NOVO (sempre OWNED, por construção) são
#     inseridas por completo.
# Resultado: cada rodada de merge é uma reconciliação completa do conjunto
# OWNED (idempotente — rodar 2x não duplica, porque a rodada 2 descarta e
# reinsere o mesmo conjunto), preservando o conjunto EXTERNO intocado.
_OWNED_HOOK_PATTERN = re.compile(r"\.harness/hooks/")


def _is_owned_hook(entry: dict) -> bool:
    cmd = _hook_command(entry) or ""
    return bool(_OWNED_HOOK_PATTERN.search(cmd))


def merge_settings_json(existing_path: Path, new_path: Path) -> dict:
    new_data = json.loads(new_path.read_text(encoding="utf-8"))

    if not existing_path.exists():
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {
            "action": "created", "path": str(existing_path),
            "hooks_added": 0, "hooks_kept": 0, "hooks_removed_stale_owned": 0,
        }

    existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
    existing_hooks: dict = existing_data.get("hooks", {})
    new_hooks: dict = new_data.get("hooks", {})

    added = 0
    kept = 0
    removed_stale_owned = 0
    merged_hooks: dict = {}

    for event in sorted(set(existing_hooks) | set(new_hooks)):
        survivor_groups: list = []

        # 1) do lado EXISTENTE, mantém só as entradas EXTERNAS (não-owned);
        #    entradas OWNED são descartadas aqui — o lado novo é quem decide
        #    o conjunto OWNED final (update/remoção/rename resolvidos).
        for matcher_group in existing_hooks.get(event, []):
            group_hooks = matcher_group.get("hooks", [])
            external_entries = [h for h in group_hooks if not _is_owned_hook(h)]
            removed_stale_owned += len(group_hooks) - len(external_entries)
            kept += len(external_entries)
            if external_entries:
                merged_group = dict(matcher_group)
                merged_group["hooks"] = external_entries
                survivor_groups.append(merged_group)

        # 2) todas as entradas do lado NOVO (sempre owned, vindas do template
        #    renderizado agora) entram por completo — fonte de verdade.
        for matcher_group in new_hooks.get(event, []):
            new_entries = matcher_group.get("hooks", [])
            if new_entries:
                survivor_groups.append(dict(matcher_group))
                added += len(new_entries)

        if survivor_groups:
            merged_hooks[event] = survivor_groups

    merged_data = dict(existing_data)
    merged_data["hooks"] = merged_hooks
    existing_path.write_text(json.dumps(merged_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "action": "merged", "path": str(existing_path),
        "hooks_added": added, "hooks_kept": kept, "hooks_removed_stale_owned": removed_stale_owned,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_md = sub.add_parser("markdown")
    p_md.add_argument("--existing", required=True, type=Path)
    p_md.add_argument("--new", required=True, type=Path)
    p_md.add_argument("--label", default="harness-init")

    p_json = sub.add_parser("settings-json")
    p_json.add_argument("--existing", required=True, type=Path)
    p_json.add_argument("--new", required=True, type=Path)

    p_gi = sub.add_parser("gitignore")
    p_gi.add_argument("--existing", required=True, type=Path)
    p_gi.add_argument("--new", required=True, type=Path)
    p_gi.add_argument("--label", default="harness-init")

    args = ap.parse_args(argv)

    if args.cmd == "markdown":
        result = merge_markdown(args.existing, args.new, args.label)
    elif args.cmd == "gitignore":
        result = merge_gitignore(args.existing, args.new, args.label)
    else:
        result = merge_settings_json(args.existing, args.new)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
