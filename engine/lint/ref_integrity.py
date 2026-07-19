#!/usr/bin/env python3
"""ref_integrity.py — integridade referencial git-aware (renames/deletes).

Porte do `guto-wiki` (padronizacao-documentacao/artefatos/scripts/
ref-integrity.py — ver docs/planning/research/01-guto-wiki.md §b) para o
`engine/` do agent-harness. Mesma troca estrutural do `docs_wiki_lint.py`
irmão: `load_config()`/`config_csv()` locais REMOVIDOS, substituídos pelo
import de `engine/_tooling_conf.py` (parser único — não repete a
triplicação DRY que o próprio guto-wiki não corrigiu). `ROOT` passa a vir
de `_tooling_conf.project_root()` em vez de `git rev-parse --show-toplevel`
inline (a MESMA chamada existia aqui — agora está centralizada no módulo
compartilhado, junto com o fallback HARNESS_PROJECT_ROOT/CLAUDE_PROJECT_DIR
que o `docs_wiki_lint.py` também usa).

FONTE ÚNICA (SOLID/DRY) consumida por 3 adaptadores finos:
  - pre-commit git hook  → --staged   (resolve/grep no INDEX; bloqueia o commit)
  - skill invocável      → --range A..B
  - loop scheduled       → --since <ref>

Duas checagens determinísticas:
  (A) broken-md-links   — links markdown `](path)` que não resolvem.
  (B) stale-citations   — citações vivas ao PATH/nome ANTIGO de arquivos renomeados/deletados
                          no git diff do seletor. Reconcilia falso-positivo vs falso-negativo:
                          basename que SUMIU do repo → busca por basename (pega citação sem path);
                          basename que AINDA existe (renomeado) → busca só por PATH completo antigo
                          (não flag `multi-tenancy.md` que resolve para o novo local).

Eixo "onde-buscar" rege AMBAS as checagens: --staged usa o INDEX (git show :path /
git cat-file -e :path / git grep --cached); --range/--since usam o working tree em HEAD.

Dois níveis de isenção:
  - is_archive (check A e B): docs/_arquivo/, .understand-anything/ (+.trash) — arqueologia pura.
  - is_historical (só check B / stale-citation): + docs/adr/, docs/auditorias/, docs/qa-evidence/, **/log.md
    — CITAÇÃO em prosa a nome antigo é snapshot legítimo, mas LINK markdown clicável quebrado ali NÃO é
    isento (check A enforça: o índice não pode ter link morto).
Exceções conhecidas (auto-output de geradores, backup manual): `.ref-integrity-allowlist`.

Exit 1 se houver referência quebrada real; 0 caso contrário. `--json` para saída máquina.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # engine/
from _tooling_conf import get_config_csv, project_root  # noqa: E402

ALLOW_EXT = {".md", ".json", ".txt", ".py", ".sh", ".toml", ".mjs", ".ts",
             ".tsx", ".css", ".yaml", ".yml", ".snyk"}
GENERIC_BASENAMES = {"index.md", "log.md", "readme.md", "schema.md", "__init__.py",
                     "config.json", "package.json", "utils.py", "types.ts"}
LINK_RE = re.compile(r"\]\(\s*([^)\s]+)")


def _fence_flags(text: str) -> list[bool]:
    """1:1 com `text.splitlines()`: True se a linha está dentro de (ou é o marcador de) um code fence.
    Fonte única da lógica de fence — não passa por join/splitlines (evita perder linha em branco final)."""
    flags: list[bool] = []
    in_fence = False
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            flags.append(True)  # o próprio marcador de fence também é zerado
        else:
            flags.append(in_fence)
    return flags


def blank_code_fences(text: str) -> str:
    """Zera o conteúdo de blocos ``` / ~~~ (1:1 por linha). Link/citação DENTRO de fence é EXEMPLO
    de código, não referência navegável — não deve flagar."""
    lines = text.splitlines()
    return "\n".join("" if fl else ln for ln, fl in zip(lines, _fence_flags(text)))


ROOT = str(project_root())


def sh(args: list[str]) -> str:
    # cwd=ROOT é uma correção introduzida por este porte, não um detalhe
    # cosmético: na fonte (guto-wiki), `ROOT = sh(["git","rev-parse",
    # "--show-toplevel"]).strip()` era DERIVADO da cwd ambiente do processo
    # — ROOT e "repo git da cwd" nunca podiam divergir. Aqui `ROOT` vem de
    # `project_root()`, que pode ser OVERRIDDEN via HARNESS_PROJECT_ROOT/
    # CLAUDE_PROJECT_DIR para um path diferente da cwd real do processo.
    # Sem `cwd=ROOT` em toda chamada git, os comandos git operariam sobre o
    # repo da cwd ambiente enquanto os paths de arquivo seriam resolvidos
    # contra `ROOT` — um mismatch silencioso. Mesma correção aplicada em
    # `exists_in_index()` e `git_grep()` abaixo (chamadas de subprocess.run
    # que não passam por `sh()`).
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout

ARCHIVE_PREFIXES = set(get_config_csv("REF_INTEGRITY_ARCHIVE_PREFIXES", ["docs/_arquivo/"]))
ARCHIVE_CONTAINS = set(get_config_csv("IGNORED_TOOL_DIRS", [".understand-anything", ".anythingllm", ".trash-"]))


def load_allowlist() -> set[str]:
    """Termos a ignorar globalmente (auto-output de geradores, backups). 1 por linha; '#' = comentário."""
    p = os.path.join(ROOT, ".ref-integrity-allowlist")
    terms: set[str] = set()
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                terms.add(line)
    return terms


def is_archive(path: str) -> bool:
    """Arqueologia pura — nem link clicável precisa resolver (docs mortos/scratch)."""
    p = path.replace("\\", "/")
    return any(p.startswith(prefix) for prefix in ARCHIVE_PREFIXES) or any(token in p for token in ARCHIVE_CONTAINS)


def is_historical(path: str) -> bool:
    """Registro histórico/snapshot: CITAÇÃO em prosa a nome antigo é legítima (check B exempta).
    Mas LINK markdown clicável quebrado NÃO é exempto aqui (check A usa is_archive, mais estreito)."""
    p = path.replace("\\", "/")
    if is_archive(p):
        return True
    # ADR imutável (Nygard), auditorias e qa-evidence = snapshots datados; log.md = append-only
    if p.startswith(("docs/adr/", "docs/auditorias/", "docs/qa-evidence/")):
        return True
    if os.path.basename(p) == "log.md":
        return True
    return False


def has_allowed_ext(path: str) -> bool:
    base = os.path.basename(path)
    if base.endswith(".snyk") or base == ".snyk":  # dotfile: splitext dá ext vazia
        return True
    return os.path.splitext(path)[1] in ALLOW_EXT


def tracked_files() -> list[str]:
    return [x for x in sh(["git", "ls-files"]).splitlines() if x]


def exists_in_index(relpath: str) -> bool:
    if subprocess.run(["git", "cat-file", "-e", f":{relpath}"],
                      cwd=ROOT, capture_output=True).returncode == 0:
        return True
    # diretório não é blob endereçável por `:path`; existe no index se há arquivo tracked sob ele
    # (senão link a dir — ex.: `sources/some-subdir/` — vira falso-positivo só no modo --staged).
    return bool(sh(["git", "ls-files", "--", f"{relpath}/"]).strip())


def path_exists(rel: str, cached: bool) -> bool:
    rel = os.path.normpath(rel)
    if not rel or rel.startswith(".."):
        return False
    return exists_in_index(rel) if cached else os.path.exists(os.path.join(ROOT, rel))


PATH_TOKEN = r"[\w./-]*"


def rd_pairs(diff_args: list[str]) -> list[tuple[str, str | None]]:
    out = sh(["git", "diff", "--name-status", "--diff-filter=RD", *diff_args])
    pairs: list[tuple[str, str | None]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        st = parts[0]
        if st.startswith("R") and len(parts) >= 3:
            pairs.append((parts[1], parts[2]))
        elif st == "D" and len(parts) >= 2:
            pairs.append((parts[1], None))
    return pairs


def git_grep(term: str, cached: bool) -> list[tuple[str, int, str]]:
    # term é o PATTERN (-e); busca no index (--cached) ou no working tree tracked.
    cmd = ["git", "grep", "-n", "-F"] + (["--cached"] if cached else []) + ["-e", term]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    hits: list[tuple[str, int, str]] = []
    for line in res.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if m:
            hits.append((m.group(1), int(m.group(2)), m.group(3)))
    return hits


_blank_cache: dict = {}


def _in_fence(f: str, ln: int, cached: bool) -> bool:
    """True se a linha `ln` de `f` está dentro de um code fence (só se aplica a .md). Usa flags 1:1
    (não o texto blanked round-tripped) — a última linha do arquivo é indexada corretamente."""
    key = (f, cached)
    if key not in _blank_cache:
        try:
            text = sh(["git", "show", f":{f}"]) if cached else open(os.path.join(ROOT, f), encoding="utf-8").read()
        except OSError:
            text = ""
        _blank_cache[key] = _fence_flags(text)
    fl = _blank_cache[key]
    return 1 <= ln <= len(fl) and fl[ln - 1]


def check_stale_citations(diff_args, cached, tracked_bases, allow) -> list[dict]:
    findings: list[dict] = []
    seen = set()
    for old, new in rd_pairs(diff_args):
        base = os.path.basename(old)
        by_basename = not (base.lower() in GENERIC_BASENAMES or base in tracked_bases)
        term = base if by_basename else old
        if term in allow or base in allow:
            continue
        for f, ln, content in git_grep(term, cached):
            if not has_allowed_ext(f) or is_historical(f) or f == new:
                continue
            if f.endswith(".md") and _in_fence(f, ln, cached):
                continue
            # token isolado (não sufixo/prefixo de nome maior, ex. e01-leaderboard.png)
            m2 = re.search(r"(?<![\w-])(" + PATH_TOKEN + re.escape(term) + PATH_TOKEN + r")(?![\w-])", content)
            if not m2:
                continue
            # se o path ao redor do match RESOLVE (foi corrigido p/ novo local, ou é outro arquivo
            # que só contém o nome como substring), não é stale.
            tok = m2.group(1).lstrip("./")
            cands = [os.path.join(os.path.dirname(f), tok), tok]
            if any(path_exists(c, cached) for c in cands):
                continue
            key = (f, ln, term)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"check": "stale-citation", "old": old, "new": new,
                             "term": term, "file": f, "line": ln,
                             "snippet": content.strip()[:120]})
    return findings


def _md_targets(text: str):
    for i, line in enumerate(text.splitlines(), 1):
        for m in LINK_RE.finditer(line):
            tgt = m.group(1).split("#")[0].strip()
            if tgt and not tgt.startswith(("http://", "https://", "mailto:", "#", "<", "tel:")):
                yield i, tgt, line


def _resolve_link(f: str, tgt: str, staged: bool) -> bool:
    tgt = urllib.parse.unquote(tgt)  # link com espaço/acento (%20) resolve para o nome real no disco
    # tenta dir-relativo E repo-relativo (docs citam paths repo-relativos sem '/' inicial)
    if tgt.startswith("/"):
        cands = [tgt.lstrip("/")]
    else:
        cands = [os.path.normpath(os.path.join(os.path.dirname(f), tgt)), os.path.normpath(tgt)]
    cands = [c for c in cands if c and not c.startswith("..")]
    return any((exists_in_index(c) if staged else os.path.exists(os.path.join(ROOT, c))) for c in cands)


def _scan_md_text(f: str, text: str, staged: bool, allow: set[str]) -> list[dict]:
    findings: list[dict] = []
    for ln, tgt, line in _md_targets(blank_code_fences(text)):  # link em fence é exemplo, não navega
        if tgt in allow:
            continue
        if tgt.startswith("{"):
            # Placeholder de runtime (`{baseDir}/...`, `{skillDir}/...`) — convenção de autoria de
            # Claude Skills onde o loader da skill resolve o token na hora, não um path literal do
            # repo. Achado real ao portar 4 skills de terceiros (agentic-actions-auditor, fp-check,
            # sarif-parsing, semgrep-rule-creator) p/ templates/: 42 dos 46 findings iniciais eram
            # este padrão. Pattern-based (não allowlist por item) porque a convenção se repete em
            # qualquer skill nova que adote `{baseDir}` — 1 regra cobre todas, não uma linha por link.
            continue
        if not _resolve_link(f, tgt, staged):
            findings.append({"check": "broken-md-link", "file": f, "line": ln,
                             "target": tgt, "snippet": line.strip()[:120]})
    return findings


def check_md_links(staged: bool, allow: set[str]) -> list[dict]:
    findings: list[dict] = []
    if staged:
        files = [f for f in sh(["git", "diff", "--cached", "--name-only",
                                "--diff-filter=ACM"]).splitlines() if f.endswith(".md")]
    else:
        files = [f for f in tracked_files() if f.endswith(".md")]
    for f in files:
        if is_archive(f):  # link clicável quebrado é ruído mesmo em log/auditoria/adr; só _arquivo é isento
            continue
        try:
            text = sh(["git", "show", f":{f}"]) if staged else open(os.path.join(ROOT, f), encoding="utf-8").read()
        except OSError:
            continue
        findings += _scan_md_text(f, text, staged, allow)
    return findings


def selftest() -> int:
    """Teste negativo institucionalizado (lição: guard só conta depois de VER o FAIL). Cria 2 .md
    temporários em docs/: um com link morto real (DEVE flagar) e um com o mesmo link morto SÓ dentro
    de code fence (NÃO deve flagar — valida blank_code_fences). Restaura o estado ao fim."""
    d = os.path.join(ROOT, "docs")
    os.makedirs(d, exist_ok=True)
    dead = os.path.join(d, ".selftest-ref-dead.md")
    fenced = os.path.join(d, ".selftest-ref-fence.md")
    open(dead, "w", encoding="utf-8").write("[x](./nao-existe-zzz-selftest.md)\n")
    open(fenced, "w", encoding="utf-8").write("```\n[x](./nao-existe-zzz-selftest.md)\n```\n")
    ok = True
    try:
        rel_dead, rel_fenced = os.path.relpath(dead, ROOT), os.path.relpath(fenced, ROOT)
        if not _scan_md_text(rel_dead, open(dead, encoding="utf-8").read(), False, set()):
            print("SELFTEST FAIL: link morto não detectado"); ok = False
        else:
            print("selftest: link morto detectado — OK")
        if _scan_md_text(rel_fenced, open(fenced, encoding="utf-8").read(), False, set()):
            print("SELFTEST FAIL: link em code fence flagado (blank_code_fences quebrado)"); ok = False
        else:
            print("selftest: link em code fence ignorado — OK")
    finally:
        os.remove(dead)
        os.remove(fenced)
    print("ref-integrity --selftest: PASS" if ok else "ref-integrity --selftest: FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Integridade referencial git-aware (renames/deletes).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="pre-commit: staged + index")
    g.add_argument("--range", metavar="A..B", help="skill: range de commits")
    g.add_argument("--since", metavar="REF", help="loop: REF..HEAD")
    g.add_argument("--selftest", action="store_true", help="teste negativo do próprio detector")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    allow = load_allowlist()
    tracked_bases = {os.path.basename(p) for p in tracked_files()}
    findings: list[dict] = []

    if a.staged:
        findings += check_stale_citations(["--cached"], True, tracked_bases, allow)
        findings += check_md_links(staged=True, allow=allow)
    else:
        rng = a.range if a.range else f"{a.since}..HEAD"
        findings += check_stale_citations([rng], False, tracked_bases, allow)
        findings += check_md_links(staged=False, allow=allow)

    # dedup global (A e B podem reportar o mesmo link p/ arquivo deletado)
    uniq, keys = [], set()
    for x in findings:
        k = (x["file"], x["line"], x.get("target") or x.get("term"))
        if k not in keys:
            keys.add(k)
            uniq.append(x)
    findings = uniq

    if a.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    elif not findings:
        print("ref-integrity: OK — nenhuma referência quebrada")
    else:
        print(f"ref-integrity: FAIL — {len(findings)} referência(s) quebrada(s):")
        for x in findings:
            if x["check"] == "broken-md-link":
                print(f"  [link]  {x['file']}:{x['line']} → {x['target']} (não resolve)")
            else:
                print(f"  [stale] {x['file']}:{x['line']} → cita '{x['term']}' (removido; novo: {x['new'] or '—'})")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
