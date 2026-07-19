#!/usr/bin/env python3
"""
Validador de nomenclatura/tipagem de data warehouse dimensional (star schema).

Implementa os checks determinísticos da spec normativa em ../SKILL.md (naming
dbt-style/medallion, tipagem PostgreSQL, SCD2). Serve como gate de code review
de DDL e de CI. Faz checagem ao NÍVEL DO NOME (tabela/coluna) e, para coluna,
checa o acoplamento nome→tipo quando o tipo é dado.

NÃO substitui o protocolo de migração (shadow+paridade) nem checa COMMENT/
lineage/PK — isso exige o banco vivo (auditoria manual via MCP Postgres). É o
"freio de mão" que impede nome/tipo fora do padrão de entrar.

ANTES DE USAR: edite VOCAB_SOURCE / VOCAB_DOMAIN / CONFORMED_DICT abaixo para
o vocabulário FECHADO real do seu projeto — os valores aqui são exemplos
ilustrativos genéricos (SaaS comuns / domínios de negócio genéricos), não uma
lista definitiva. Ver "Antes de modelar" em ../SKILL.md.

Uso:
    python validate_dw.py --table public.fct_salesforce__opportunity
    python validate_dw.py --table fct_sales__pipeline
    python validate_dw.py --column customer_code --type text
    python validate_dw.py --column created_at --type "timestamp without time zone"
    python validate_dw.py --file nomes.txt      # uma entrada por linha: "table:..." ou "column:...[|tipo]"
    python validate_dw.py --self-test

Stdlib apenas. Exit code 0 = sem erros; 1 = há violações (erros).
Warnings não derrubam o exit code (são pontos de atenção, não bloqueio).
"""
import argparse
import re
import sys

try:  # saída UTF-8 mesmo em console Windows (cp1252) / pipe de CI
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# Vocabulário FECHADO (edite para o seu projeto). Token fora destas listas é
# rejeitado; adicionar token é decisão consciente (edite aqui ou PR ao time).
# ─────────────────────────────────────────────────────────────────────────────
LAYER_PREFIXES = ("raw_", "stg_", "dim_", "fct_", "rpt_", "ref_", "int_")

# Exemplo ilustrativo: SaaS/sistemas externos comuns (mono-fonte). Troque
# pelos fornecedores/plataformas reais que o SEU projeto integra.
VOCAB_SOURCE = {
    "salesforce", "stripe", "hubspot", "zendesk", "internal",
}

# Exemplo ilustrativo: domínios de negócio genéricos (cross-fonte / cálculo
# interno). Troque pelos domínios reais do SEU negócio.
VOCAB_DOMAIN = {
    "sales", "finance", "marketing", "product", "ops",
}

VOCAB_ROLE = {"latest", "history"}
VOCAB_GRAIN = {"daily", "weekly", "monthly", "intraday"}

# Sufixos proibidos em schema produtivo
FORBIDDEN_SUFFIX_TOKENS = {
    "hist", "final", "new", "old", "bkp", "bak", "copy", "test", "baseline",
    "pybak", "hs", "optimized", "fast",
}
FORBIDDEN_SUFFIX_RE = re.compile(r"_(v\d+|\d{8})$")  # _v2, _v3, _20260524 ...

# Colunas genéricas proibidas sozinhas (convenção pública do time de dados do
# GitLab: nome sem classe-de-objeto é ambíguo em qualquer catálogo)
BARE_FORBIDDEN_COLS = {"date", "data", "month", "value", "id", "name", "type"}

# Prefixos de booleano
BOOL_PREFIXES = ("is_", "has_", "was_", "does_")

# Nomes de auditoria canônicos -> timestamptz (universais, não precisam de edição)
AUDIT_NAMES = {
    "created_at", "updated_at", "deleted_at",
    "loaded_at", "extracted_at", "synced_at",
}

# Dicionário conformado: conceito -> tipo canônico. Mesmo nome => mesmo tipo
# em TODO o DW. As entradas de auditoria/SCD2 são universais; as de negócio
# (customer_*, order_id, region_code, reference_*) são EXEMPLO — troque pelos
# conceitos recorrentes reais do seu projeto.
CONFORMED_DICT = {
    "customer_id": "uuid",
    "customer_code": "text",
    "customer_name": "text",
    "region_code": "text",
    "reference_date": "date",
    "reference_month": "date",
    "created_at": "timestamptz",
    "updated_at": "timestamptz",
    "loaded_at": "timestamptz",
    "extracted_at": "timestamptz",
    "synced_at": "timestamptz",
    "valid_from": "timestamptz",
    "valid_to": "timestamptz",
    "is_current": "boolean",
}

# Acoplamento termo-de-representação -> tipo obrigatório (universal, ISO 11179).
# Cada par é (sufixo, conjunto de tipos aceitos, rótulo p/ mensagem).
REP_TERM_TYPES = [
    ("_sk", {"bigint"}, "bigint GENERATED ALWAYS AS IDENTITY (IDENTITY auditado no catálogo)"),
    ("_at", {"timestamptz", "timestamp with time zone"}, "timestamptz"),
    ("_date", {"date"}, "date"),
    ("_month", {"date"}, "date (1º dia do mês)"),
    ("_amount", {"numeric(18,4)", "numeric(18,2)"}, "numeric(18,4)"),
    ("_rate", {"numeric(18,6)"}, "numeric(18,6)"),
    ("_pct", {"numeric(9,6)"}, "numeric(9,6)"),
    ("_count", {"integer", "int", "bigint", "smallint"}, "integer/bigint"),
    ("_id", {"bigint", "text", "uuid"}, "bigint interno novo / text ID externo / uuid nasce-fora"),
    ("_key", {"date"}, "date (chave de data/grão)"),
]

# Tipos proibidos em geral (universal — docs oficiais do PostgreSQL)
FORBIDDEN_TYPES = {
    "money": "dinheiro: use numeric(18,4) — wiki PG: \"Don't use money\"",
    "real": "float financeiro proibido: use numeric",
    "double precision": "float financeiro proibido: use numeric",
    "float": "float financeiro proibido: use numeric",
    "json": "use jsonb (PG docs: \"most applications should prefer jsonb\")",
    "timestamp": "use timestamptz — timestamp descarta o fuso silenciosamente",
    "timestamp without time zone": "use timestamptz",
    "serial": "use bigint GENERATED ALWAYS AS IDENTITY",
    "bigserial": "use bigint GENERATED ALWAYS AS IDENTITY",
}

NAME_CHARSET = re.compile(r"^[a-z][a-z0-9_]*$")
COL_CHARSET = re.compile(r"^[a-z][a-z0-9_]*$")


class Report:
    def __init__(self, subject):
        self.subject = subject
        self.errors = []
        self.warnings = []

    def err(self, rule, msg):
        self.errors.append((rule, msg))

    def warn(self, rule, msg):
        self.warnings.append((rule, msg))

    def ok(self):
        return not self.errors

    def render(self):
        head = "PASS" if self.ok() else "FAIL"
        lines = [f"[{head}] {self.subject}"]
        for rule, msg in self.errors:
            lines.append(f"  [x] ({rule}) {msg}")
        for rule, msg in self.warnings:
            lines.append(f"  [!] ({rule}) {msg}")
        if self.ok() and not self.warnings:
            lines.append("  [ok] conforme")
        return "\n".join(lines)


def _norm_type(t):
    if not t:
        return None
    out = re.sub(r"\s+", " ", t.strip().lower())
    out = re.sub(r"\(\s*", "(", out)
    out = re.sub(r"\s*\)", ")", out)
    out = re.sub(r"\s*,\s*", ",", out)
    return out


def validate_table(name):
    """Valida um nome de tabela/view/matview do território do DW (T1)."""
    schema = None
    raw = name
    if "." in name:
        schema, name = name.split(".", 1)
    r = Report(f"table {raw}")

    # Lápide: fora do check de gramática.
    if name.startswith("zz_deprecated__"):
        r.warn("R3", "lápide zz_deprecated__ — fora do check de gramática; "
                      "dropar em ≤1 release")
        return r

    # Estado operacional interno (arquétipo K): prefixo '_' líder — exceção
    # autorizada ao charset; checa antes do ^[a-z]... .
    if name.startswith("_"):
        if not re.match(r"^_[a-z][a-z0-9_]*$", name):
            r.err("R5.1", "ops '_<entity>': após o '_' líder vale ^[a-z][a-z0-9_]*$")
        r.warn("R2.1/R7", "prefixo '_' = estado operacional interno (fora do "
                          "medallion); ok se for sync/migração/lock/auditoria")
        return r

    # R5.1 charset + tamanho
    if not NAME_CHARSET.match(name):
        r.err("R5.1", f"charset: deve casar ^[a-z][a-z0-9_]*$ "
                       f"(minúsculo, sem aspas/acento/espaço, não começa com dígito)")
    if len(name.encode("utf-8")) > 63:
        r.err("R5.1", "comprimento > 63 bytes (NAMEDATALEN); alvo prático ≤ 50")

    # R1.2 separadores — conta '__' (exceção: __c de objeto custom Salesforce)
    is_sf_custom = name.startswith("stg_salesforce__") and name.endswith("__c")
    dunder = name.count("__")
    if is_sf_custom:
        if dunder > 2:
            r.err("R1.2", "stg_salesforce__*__c admite no máx. 2 '__' (o 2º é o __c)")
    elif dunder > 1:
        r.err("R1.2", f"{dunder} '__' no nome — máx. 1 (fronteira namespace↔entidade). "
                      f"'_' simples separa palavras dentro de uma parte")

    # R2.1 prefixo de camada
    prefix = next((p for p in LAYER_PREFIXES if name.startswith(p)), None)
    if not prefix:
        r.err("R2.1", "sem prefixo de camada válido (raw_/stg_/dim_/fct_/rpt_/ref_/int_) "
                      "nem '_' de ops. Objeto novo do T1 codifica a camada por prefixo")
        return r

    rest = name[len(prefix):]

    # R2.4 sufixos proibidos (versão/backup/teste/data)
    tokens = rest.split("_")
    bad = [t for t in tokens if t in FORBIDDEN_SUFFIX_TOKENS]
    if bad:
        r.err("R2.4", f"token(s) proibido(s) {bad}: versão/backup/shadow/teste vivem "
                      f"em schema 'sandbox' com TTL, nunca no nome em produção")
    if FORBIDDEN_SUFFIX_RE.search(name):
        r.err("R2.4", "sufixo de versão/data embutida (_v<N> / _YYYYMMDD) proibido — "
                      "use sandbox + TTL ou _latest/_history")

    # Namespace por camada
    if prefix in ("dim_",):
        # dimensão conformada: SEM token de fonte
        if "__" in rest:
            r.warn("R1/R1.1", "dim_ é dimensão CONFORMADA e não leva namespace de fonte. "
                              "Reveja se '__' é necessário")
    elif prefix in ("stg_", "raw_"):
        ns = rest.split("__")[0] if "__" in rest else None
        if ns is None:
            r.err("R1", f"{prefix} exige <source>__<entity> (espelho 1:1 da fonte)")
        elif ns not in VOCAB_SOURCE:
            r.err("R2.2", f"fonte '{ns}' fora do VOCAB_SOURCE (FECHADO). "
                          f"Adicionar token é decisão consciente — edite o script")
    elif prefix in ("fct_", "rpt_"):
        ns = rest.split("__")[0] if "__" in rest else None
        if ns is None:
            first = rest.split("_", 1)[0]
            if first in VOCAB_SOURCE or first in VOCAB_DOMAIN:
                r.err("R1.2", f"'{first}' é namespace de fonte/domínio: use '__' "
                              f"({prefix}{first}__<entity>). '_' simples onde devia "
                              f"ser '__' (fronteira semântica)")
            else:
                r.warn("R1.3", f"{prefix} sem '__': fato/report consolidado pré-spec "
                               f"(grandfathered). Nome novo usa <namespace>__<entity>")
        elif ns not in VOCAB_SOURCE and ns not in VOCAB_DOMAIN:
            r.err("R2.2/R2.3", f"namespace '{ns}' não é source nem domain do vocabulário "
                              f"fechado. Mono-fonte→source; cruza fontes→domain")

    return r


def validate_column(name, coltype=None):
    """Valida um nome de coluna (e o acoplamento nome→tipo, se o tipo é dado)."""
    r = Report(f"column {name}" + (f" :: {coltype}" if coltype else ""))
    t = _norm_type(coltype)

    # R5.1 charset / dígito-inicial
    if not COL_CHARSET.match(name):
        r.err("R5.1", "charset: ^[a-z][a-z0-9_]*$ (sem acento/maiúscula/espaço; "
                      "não começa com dígito)")

    # R3.2 genérico sozinho proibido
    if name in BARE_FORBIDDEN_COLS:
        r.err("R3.2", f"'{name}' sozinho é genérico sem classe-de-objeto. "
                      f"Prefixe com a entidade: <object_class>_{name}")

    # R3.3 dicionário conformado tem prioridade
    if name in CONFORMED_DICT:
        canon = CONFORMED_DICT[name]
        if t and not _type_matches(t, canon):
            r.err("R3.3", f"'{name}' é conceito conformado: tipo canônico = {canon} "
                          f"(recebido: {coltype})")

    # R3.5 booleano
    if t in {"boolean", "bool"}:
        if not name.startswith(BOOL_PREFIXES):
            r.err("R3.5", "booleano deve ter prefixo is_/has_/was_/does_")
    if name.startswith(BOOL_PREFIXES) and t and t not in {"boolean", "bool"}:
        r.err("R3.5", f"nome com prefixo de booleano mas tipo {coltype} ≠ boolean")

    # R3.2 _key reservado
    if name.endswith("_key"):
        r.warn("R3.2/R11.3", "sufixo _key é RESERVADO (não usar em coluna nova; "
                            "surrogate→<entity>_sk; id de entidade→<entity>_id; "
                            "data/grão→*_key date)")

    # R3.2 acoplamento termo-de-representação -> tipo
    if t:
        for suffix, accepted, label in REP_TERM_TYPES:
            if name.endswith(suffix):
                if not any(_type_matches(t, a) for a in accepted):
                    r.err("R3.2/R4", f"sufixo '{suffix}' exige {label} (recebido: {coltype})")
                break
        if name in AUDIT_NAMES and not _type_matches(t, "timestamptz"):
            r.err("R3.2", f"'{name}' é audit: exige timestamptz (recebido: {coltype})")
        # tipos proibidos em geral
        if t in FORBIDDEN_TYPES:
            r.err("R4", f"tipo proibido '{coltype}': {FORBIDDEN_TYPES[t]}")
        if t.startswith("varchar(") or t.startswith("character varying("):
            r.warn("R4", "varchar(n): só com regra de negócio para o n; default é text. "
                        "Prefira text + CHECK (wiki PG: \"Don't use varchar(n) by default\")")
        if t.startswith("char(") or t.startswith("character("):
            r.err("R4", "char(n) proibido SEM exceção (padding de espaços) — use text")

    return r


def _type_matches(got, canonical):
    """Compara tipo recebido com o canônico, tolerando sinônimos comuns."""
    got = _norm_type(got)
    canonical = _norm_type(canonical)
    synonyms = {
        "timestamptz": {"timestamptz", "timestamp with time zone"},
        "int": {"int", "integer", "int4"},
        "integer": {"int", "integer", "int4"},
        "bigint": {"bigint", "int8"},
        "boolean": {"boolean", "bool"},
        "numeric": {"numeric", "decimal"},
    }
    if canonical.startswith(("numeric(", "decimal(")):
        return got.replace("decimal", "numeric", 1) == canonical.replace("decimal", "numeric", 1)
    if canonical == "bigint" and got.startswith("bigint generated "):
        return True
    if canonical in synonyms and got in synonyms[canonical]:
        return True
    if canonical in {"numeric", "decimal"}:
        # Família genérica só quando a regra canônica pedir numeric/decimal sem escala.
        return got.startswith("numeric") or got.startswith("decimal")
    return got == canonical


def run_self_test():
    """Roda exemplos-padrão (bom → conforme, ruim → falha) usando o
    vocabulário ilustrativo default deste script."""
    cases_tables_ok = [
        "public.fct_salesforce__opportunity", "fct_sales__pipeline", "dim_customer",
        "stg_salesforce__lead", "rpt_sales__pipeline", "ref_currency_daily",
        "stg_salesforce__lead__c", "_sync_runs",
    ]
    cases_tables_bad = [
        "fct_salesforce_calls",          # _ simples (R1.2)
        "fct_salesforce__calls_v2",      # _v2 (R2.4)
        "dim_customers_new_version",     # _new (R2.4)
        "stg_hubspotcontact",            # fonte colada sem __ (R2.2/R1)
        "fct_unknown__opportunity",      # 'unknown' fora do vocab (R2.2/R2.3)
        "Fct_Account",                   # casing (R5.1)
    ]
    cases_cols = [
        ("customer_code", "bigint", False),   # dicionário exige text
        ("customer_code", "text", True),
        ("created_at", "timestamp", False),   # exige timestamptz
        ("order_amount", "double precision", False),  # dinheiro float
        ("order_amount", "numeric", False),   # dinheiro exige escala explícita
        ("order_amount", "numeric(18,4)", True),
        ("account_sk", "integer", False),     # _sk novo é bigint
        ("account_sk", "bigint", True),
        ("order_id", "integer", False),       # _id interno novo é bigint
        ("order_id", "bigint", True),
        ("external_ref_id", "text", True),
        ("date_key", "date", True),           # passa com warning; _key reservado a data/grão
        ("is_active", "boolean", True),
        ("active", "boolean", False),         # booleano sem prefixo
        ("status", "boolean", False),         # genérico + boolean
        ("60_days_date", "date", False),      # começa com dígito
    ]
    failures = 0
    print("-- tabelas que DEVEM passar --")
    for n in cases_tables_ok:
        rep = validate_table(n)
        print(rep.render())
        if not rep.ok():
            failures += 1
    print("\n-- tabelas que DEVEM falhar --")
    for n in cases_tables_bad:
        rep = validate_table(n)
        print(rep.render())
        if rep.ok():
            failures += 1
    print("\n-- colunas --")
    for n, t, should_pass in cases_cols:
        rep = validate_column(n, t)
        print(rep.render())
        if rep.ok() != should_pass:
            failures += 1
    print(f"\nself-test: {'OK' if failures == 0 else f'{failures} divergência(s)'}")
    return 0 if failures == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validador de nomenclatura/tipagem de DW dimensional")
    ap.add_argument("--table", action="append", default=[], help="nome de tabela ([schema.]nome)")
    ap.add_argument("--column", help="nome de coluna")
    ap.add_argument("--type", help="tipo da coluna (usado com --column)")
    ap.add_argument("--file", help="arquivo com entradas: 'table:NOME' ou 'column:NOME[|TIPO]'")
    ap.add_argument("--self-test", action="store_true", help="roda os exemplos-padrão")
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()

    reports = []
    for t in args.table:
        reports.append(validate_table(t))
    if args.column:
        reports.append(validate_column(args.column, args.type))
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                kind, _, payload = line.partition(":")
                if kind == "table":
                    reports.append(validate_table(payload.strip()))
                elif kind == "column":
                    nm, _, ty = payload.partition("|")
                    reports.append(validate_column(nm.strip(), ty.strip() or None))

    if not reports:
        ap.print_help()
        return 2

    any_error = False
    for rep in reports:
        print(rep.render())
        any_error = any_error or not rep.ok()
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
