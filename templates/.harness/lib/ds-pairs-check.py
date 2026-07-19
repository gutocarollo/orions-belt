#!/usr/bin/env python3
"""ds-pairs-check — guarda genérica do CONTRATO DOS PARES COLORIDOS (globals.css).

PORTADO de apps/web/scripts/ds-pairs-check.py (harness-doador de referência) —
plano de resgate §R1a. Regra estrutural (contrato de design system shadcn-style):
  - Pares coloridos de ação/status (primary, destructive, success, info, premium):
    `X-foreground` DEVE ser branco (família #fff) e contrastar >= 4,5:1 com `X`.
    O rótulo contrasta com o PAI (container), nunca com a página.
  - Exceção:
    - warning (âmbar + rótulo escuro é o par canônico; exige >= 4,5:1 idem).
  - surface-selected é NEUTRO invertido (par inverte junto) — checa só o contraste.

GENERICIDADE (vs. a versão-fonte): zero string de marca hardcoded.
  - Path do CSS: HARNESS_WEB_APP_DIR + DS_GATE_CSS_PATH (.harness/harness.conf),
    default "styles/globals.css" relativo ao app web. Ausente = fail-open
    (nada a checar, exit 0), não crash.
  - Blocos de tema: PROJECT_THEMES (CSV de valores de atributo data-theme).
    Vazio = só avalia a base :root/.dark (sem overlay de marca) — nenhum nome
    de marca fica hardcoded no engine.

Uso: python3 .harness/lib/ds-pairs-check.py   (exit 1 se qualquer par violar)
"""
from __future__ import annotations

import math
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tooling_conf import get_config, get_config_csv, project_root  # noqa: E402

ROOT = project_root()
WEB_APP_DIR = (get_config("HARNESS_WEB_APP_DIR", ".") or ".").strip("/") or "."
CSS_REL = get_config("DS_GATE_CSS_PATH", "styles/globals.css") or "styles/globals.css"
CSS = (ROOT if WEB_APP_DIR == "." else ROOT / WEB_APP_DIR) / CSS_REL

if not CSS.is_file():
    print(f"ds-pairs-check: CSS de tokens não encontrado em {CSS} — nada a checar (fail-open).")
    sys.exit(0)

PAIRS = ['primary', 'destructive', 'success', 'info', 'premium', 'warning', 'surface-selected']
WHITE_REQUIRED = {'primary', 'destructive', 'success', 'info', 'premium'}

src = CSS.read_text()
# remove comentários /* */ (o regex de par pegava exemplos dentro de comentário)
src_nc = re.sub(r'/\*.*?\*/', '', src, flags=re.S)


def block_body(start_pat):
    m = re.search(start_pat, src_nc)
    if not m:
        return ''
    depth = 0
    i = src_nc.index('{', m.start())
    for j in range(i, len(src_nc)):
        if src_nc[j] == '{':
            depth += 1
        elif src_nc[j] == '}':
            depth -= 1
            if depth == 0:
                return src_nc[i:j]
    return ''


def all_bodies(start_pat):
    out = []
    for m in re.finditer(start_pat, src_nc):
        i = src_nc.index('{', m.start())
        depth = 0
        for j in range(i, len(src_nc)):
            if src_nc[j] == '{':
                depth += 1
            elif src_nc[j] == '}':
                depth -= 1
                if depth == 0:
                    out.append(src_nc[i:j])
                    break
    return out


OKLCH_RE = re.compile(
    r'oklch\(\s*([\d.]+)(%)?\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*(?:/[^)]*)?\)',
    re.IGNORECASE,
)


def oklch_to_hex(l, c, h):
    """OKLCH -> sRGB hex. Fórmulas determinísticas de Björn Ottosson
    (OKLab -> LMS linear -> sRGB linear -> sRGB gamma), a mesma base que
    TweakCN/oklch.com usam para gerar os tokens que o AGENTS.md recomenda.
    Alpha (`/ N`) é ignorado — resolve como opaco; par com alpha < 1
    realmente depende do backdrop e não é tentado aqui (ver `resolve`)."""
    hr = math.radians(h)
    a = c * math.cos(hr)
    b = c * math.sin(hr)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    ll, mm, ss = l_ ** 3, m_ ** 3, s_ ** 3
    r_lin = 4.0767416621 * ll - 3.3077115913 * mm + 0.2309699292 * ss
    g_lin = -1.2684380046 * ll + 2.6097574011 * mm - 0.3413193965 * ss
    b_lin = -0.0041960863 * ll - 0.7034186147 * mm + 1.7076147010 * ss

    def to_srgb_byte(ch):
        ch = max(0.0, min(1.0, ch))
        v = 12.92 * ch if ch <= 0.0031308 else 1.055 * (ch ** (1 / 2.4)) - 0.055
        return max(0, min(255, round(v * 255)))

    return '#%02x%02x%02x' % (to_srgb_byte(r_lin), to_srgb_byte(g_lin), to_srgb_byte(b_lin))


def resolve(val, scope):
    val = val.strip()
    m = re.match(r'var\((--[\w-]+)\)', val)
    if m:
        d = re.search(re.escape(m.group(1)) + r':\s*([^;]+);', scope) or \
            re.search(re.escape(m.group(1)) + r':\s*([^;]+);', src_nc)
        return resolve(d.group(1), scope) if d else None
    m = re.match(r'#([0-9a-fA-F]{6})\b', val)
    if m:
        return m.group(0).lower()
    # H2/A6.1 (auditoria adversarial pós-v1.0.0): a versão anterior só
    # resolvia var()/hex — um par definido em OKLCH (o formato que o
    # AGENTS.md deste mesmo repo recomenda via TweakCN) virava SKIP
    # silencioso e o resumo dizia "CONTRATO OK em todos os pares", mesmo
    # com um par de contraste ~zero não avaliado. Fix: parseia
    # `oklch(L C H)` (L em [0,1] ou "L%", H em graus, alpha ignorado) e
    # converte para hex via `oklch_to_hex` para entrar no mesmo pipeline de
    # contraste que hex/var() já usam.
    m = OKLCH_RE.match(val)
    if m:
        l = float(m.group(1))
        if m.group(2):  # "L%"
            l = l / 100.0
        c = float(m.group(3))
        h = float(m.group(4))
        try:
            return oklch_to_hex(l, c, h)
        except (ValueError, OverflowError):
            return None
    return None


def lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


SOFT_PAIRS = ['success-soft', 'info-soft', 'warning-soft', 'destructive-soft', 'premium-soft']
FILLS = ['success-fill', 'warning-fill', 'destructive-fill', 'info-fill', 'premium-fill']

# ── blocos de tema: genéricos via PROJECT_THEMES (CSV de data-theme). Vazio =
# só a base :root/.dark (sem overlay de marca) — sem nenhum nome de marca
# hardcoded no engine (o contrário da versão-fonte, que citava o nome da
# marca do harness-doador literalmente). ──
THEMES = get_config_csv('PROJECT_THEMES', [])
BLOCKS: dict[str, str] = {}
if THEMES:
    for t in THEMES:
        t_re = re.escape(t)
        BLOCKS[f'{t} (claro)'] = rf'\[data-theme="{t_re}"\]\s*\{{'
        BLOCKS[f'{t}.dark'] = rf'\[data-theme="{t_re}"\]\.dark'
else:
    BLOCKS['base (claro, :root)'] = r':root\s*\{'
    BLOCKS['base.dark'] = r'(?<![\]"])\.dark\s*\{'

BLOCKS = {k: v for k, v in BLOCKS.items()}  # (materializa; block_body chamado abaixo por nome)

# Herança da cascata: os blocos de marca sobrescrevem :root/.dark; tokens não
# declarados localmente herdam da base. Sem folding, o guarda pula
# silenciosamente o token herdado e dá falso "OK". Simplificação genérica: usa
# o PRIMEIRO :root/.dark encontrado como base (a versão-fonte fingerprintava
# por `--background: #ffffff` para desambiguar múltiplos :root — não
# preservado aqui: caso raro, e exigiria hardcodar o nome do token
# `--background`; se o projeto tiver múltiplos :root reais, ajuste manual).
_all_root = all_bodies(r':root\s*\{')
_all_dark = all_bodies(r'(?<![\]"])\.dark\s*\{')
BASE_LIGHT = _all_root[0] if _all_root else ''
BASE_DARK = _all_dark[0] if _all_dark else ''
BASE = {name: (BASE_DARK if name.endswith('.dark') else BASE_LIGHT) for name in BLOCKS}


def eff(name, body, base):
    """valor efetivo (cascata): bloco próprio vence; senão herda da base."""
    m = re.search(rf'--{name}:\s*([^;]+);', body)
    if not m and base:
        m = re.search(rf'--{name}:\s*([^;]+);', base)
    return m


fails = 0
skips = 0  # H2/A6.1: pares que existem no CSS mas não puderam ser resolvidos
           # para uma cor avaliável (nem var()/hex/oklch) — NÃO contam como "OK".
print(f'{"BLOCO":24} {"PAR":18} {"tom":9} {"rótulo":9} {"ratio":>6}  veredicto')
print('-' * 82)
for bname, bpat in BLOCKS.items():
    body = block_body(bpat)
    if not body:
        continue
    base = BASE.get(bname, '')
    scope = body + '\n' + base  # var() herdado resolve na base
    for p in PAIRS:
        mx = eff(p, body, base)
        mf = eff(p + '-foreground', body, base)
        if not mx or not mf:
            continue
        x = resolve(mx.group(1), scope)
        fg = resolve(mf.group(1), scope)
        if not x or not fg:
            skips += 1
            print(f'{bname:24} {p:18} {"?":9} {"?":9} {"—":>6}  SKIP (não-resolvível: rgba/alias externo)')
            continue
        r = contrast(x, fg)
        ok_contrast = r >= 4.5
        ok_white = (
            (p not in WHITE_REQUIRED)
            or (fg in ('#ffffff', '#fafafa', '#fffbeb', '#f8f8f2'))
        )
        verdict = 'OK' if (ok_contrast and ok_white) else 'VIOLA'
        if verdict == 'VIOLA':
            fails += 1
        why = '' if verdict == 'OK' else (' rótulo-não-branco' if not ok_white else '') + ('' if ok_contrast else ' contraste<4,5')
        print(f'{bname:24} {p:18} {x:9} {fg:9} {r:6.2f}  {verdict}{why}')
    # pares *-soft — texto sobre o próprio chip (>=4,5)
    for p in SOFT_PAIRS:
        mx = eff(p, body, base)
        mf = eff(p + '-foreground', body, base)
        if not mx or not mf:
            continue
        x = resolve(mx.group(1), scope)
        fg = resolve(mf.group(1), scope)
        if not x or not fg:
            skips += 1
            print(f'{bname:24} {p:18} {"?":9} {"?":9} {"—":>6}  SKIP (não-resolvível: rgba/alias externo)')
            continue
        r = contrast(x, fg)
        verdict = 'OK' if r >= 4.5 else 'VIOLA'
        if verdict == 'VIOLA':
            fails += 1
        print(f'{bname:24} {p:18} {x:9} {fg:9} {r:6.2f}  {verdict}{"" if r >= 4.5 else " contraste<4,5"}')
    # fills de progresso vs --muted (superfície real da barra). non-text >=3.
    mt = eff('muted', body, base)
    surf = resolve(mt.group(1), scope) if mt else None
    if surf:
        for p in FILLS:
            mx = eff(p, body, base)
            if not mx:
                continue
            x = resolve(mx.group(1), scope)
            if not x:
                continue
            r = contrast(x, surf)
            verdict = 'OK' if r >= 3.0 else 'VIOLA'
            if verdict == 'VIOLA':
                fails += 1
            print(f'{bname:24} {p + " vs muted":18} {x:9} {surf:9} {r:6.2f}  {verdict}{"" if r >= 3.0 else " fill<3,0"}')
print('-' * 82)
# H2/A6.1: SKIP nunca vira "OK em todos os pares" no resumo — antes da
# adição do parser OKLCH, um par não-resolvível (ex.: OKLCH de contraste
# ~zero) silenciosamente virava SKIP e o resumo dizia "OK", contradizendo o
# próprio AGENTS.md (que recomenda OKLCH/TweakCN). Com o parser OKLCH, SKIP
# só deve sobrar para formato REALMENTE não-resolvível (rgba translúcido,
# alias externo, alpha<1) — e mesmo assim o resumo reporta explicitamente,
# nunca "OK".
if fails:
    print('CONTRATO', 'VIOLADO em %d par(es)' % fails)
elif skips:
    print(f'CONTRATO: {skips} par(es) NAO AVALIADOS (formato nao-resolvivel) -- nao e "OK", revise manualmente')
else:
    print('CONTRATO', 'OK em todos os pares')
sys.exit(1 if fails else (2 if skips else 0))
