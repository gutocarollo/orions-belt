#!/usr/bin/env python3
"""ds-pair-eval — evaluates whether a PAIR (text color x background color)
keeps contrast across the configured production themes.

PORTED from apps/web/scripts/ds-pair-eval.py (reference donor harness) —
rescue plan §R1a. Complements ds-pairs-check.py (which validates the pairs in
the CSS DEFINITION); THIS one evaluates the pair at the POINT OF USE — e.g.
"text-foreground over bg-white" or "text-white/70 over bg-surface-selected" —
deterministically judging when a pair "fits" (PASS in all themes) and when it
does not (FAIL, with the themes that fail).

GENERICITY (vs. the source version): zero hardcoded brand name.
  - CSS path: HARNESS_WEB_APP_DIR + DS_GATE_CSS_PATH (.harness/harness.conf).
    Missing = fail-open (every pair becomes "unresolvable", not a crash).
  - Themes: PROJECT_THEMES (CSV of data-theme attribute values). Each theme
    T generates two entries — "T" (light variant, `[data-theme="T"] {`) and
    "T-dark" (dark variant, `[data-theme="T"].dark`) — plus the two base
    entries always present: "light" (:root) and "dark-base" (neutral .dark).
    Empty = evaluates only light/dark-base (no brand overlay).

CLI:
  python3 .harness/lib/ds-pair-eval.py --text text-foreground --bg bg-white
  python3 .harness/lib/ds-pair-eval.py --text text-white/70 --bg bg-surface-selected --non-text
  echo '[{"text":"text-muted-foreground","bg":"bg-card"}]' | python3 .harness/lib/ds-pair-eval.py --batch

Exit 1 if any pair FAILS in any theme (useful in a gate).
"""
from __future__ import annotations

import re
import sys
import json
import pathlib
import argparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tooling_conf import get_config, get_config_csv, project_root  # noqa: E402

ROOT = project_root()
WEB_APP_DIR = (get_config("HARNESS_WEB_APP_DIR", ".") or ".").strip("/") or "."
CSS_REL = get_config("DS_GATE_CSS_PATH", "styles/globals.css") or "styles/globals.css"
CSS = (ROOT if WEB_APP_DIR == "." else ROOT / WEB_APP_DIR) / CSS_REL

if CSS.is_file():
    SRC = re.sub(r'/\*.*?\*/', '', CSS.read_text(), flags=re.S)  # without comments
else:
    print(f"ds-pair-eval: tokens CSS not found at {CSS} — pairs become unresolvable (fail-open).", file=sys.stderr)
    SRC = ''

# ── themes: base (light=:root, dark-base=neutral .dark) always present; each
# PROJECT_THEMES theme adds a light + dark variant via data-theme. ──
THEMES = get_config_csv('PROJECT_THEMES', [])
THEME_SEL: dict[str, str] = {
    'light': r':root\s*\{',
    'dark-base': r'(?<![\]"])\.dark\s*\{',
}
BASE_OF: dict[str, str] = {'dark-base': 'light'}
for _t in THEMES:
    _t_re = re.escape(_t)
    THEME_SEL[_t] = rf'\[data-theme="{_t_re}"\]\s*\{{'
    THEME_SEL[f'{_t}-dark'] = rf'\[data-theme="{_t_re}"\]\.dark'
    BASE_OF[_t] = 'light'
    BASE_OF[f'{_t}-dark'] = 'dark-base'


def _block(sel):
    m = re.search(sel, SRC)
    if not m:
        return ''
    i = SRC.index('{', m.start())
    depth = 0
    for j in range(i, len(SRC)):
        if SRC[j] == '{':
            depth += 1
        elif SRC[j] == '}':
            depth -= 1
            if depth == 0:
                return SRC[i:j]
    return ''


BLOCKS = {k: _block(v) for k, v in THEME_SEL.items()}


def _resolve_var(name, theme):
    """hex value of the --name token in the theme (with inheritance + var() chains)."""
    scopes = [BLOCKS.get(theme, '')]
    b = BASE_OF.get(theme)
    while b:
        scopes.append(BLOCKS.get(b, ''))
        b = BASE_OF.get(b)
    scopes.append(SRC)  # last resort: any definition
    for scope in scopes:
        m = re.search(r'--' + re.escape(name) + r':\s*([^;]+);', scope)
        if not m:
            continue
        val = m.group(1).strip()
        vm = re.match(r'var\((--[\w-]+)\)', val)
        if vm:
            return _resolve_var(vm.group(1)[2:], theme)
        hm = re.match(r'#([0-9a-fA-F]{6})\b', val)
        if hm:
            return '#' + hm.group(1).lower()
        return None  # rgb(...)/rgba(...) → non-hex, signals unresolvable
    return None


# ── Tailwind palette (neutral families + white/black — generic, not brand
# vocabulary) ──
PALETTE = {
    'white': '#ffffff', 'black': '#000000', 'transparent': None,
}
_RAMPS = {
    'slate': ['f8fafc', 'f1f5f9', 'e2e8f0', 'cbd5e1', '94a3b8', '64748b', '475569', '334155', '1e293b', '0f172a', '020617'],
    'gray': ['f9fafb', 'f3f4f6', 'e5e7eb', 'd1d5db', '9ca3af', '6b7280', '4b5563', '374151', '1f2937', '111827', '030712'],
    'zinc': ['fafafa', 'f4f4f5', 'e4e4e7', 'd4d4d8', 'a1a1aa', '71717a', '52525b', '3f3f46', '27272a', '18181b', '09090b'],
    'neutral': ['fafafa', 'f5f5f5', 'e5e5e5', 'd4d4d4', 'a3a3a3', '737373', '525252', '404040', '262626', '171717', '0a0a0a'],
    'stone': ['fafaf9', 'f5f5f4', 'e7e5e4', 'd6d3d1', 'a8a29e', '78716c', '57534e', '44403c', '292524', '1c1917', '0c0a09'],
}
_STOPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
for fam, hexes in _RAMPS.items():
    for stop, h in zip(_STOPS, hexes):
        PALETTE[f'{fam}-{stop}'] = '#' + h

# valid semantic tokens (--var names that appear as a bg-/text- class)
TOKENS = {'background', 'foreground', 'card', 'card-foreground', 'popover', 'popover-foreground',
          'primary', 'primary-foreground', 'secondary', 'secondary-foreground', 'muted', 'muted-foreground',
          'accent', 'accent-foreground', 'destructive', 'destructive-foreground', 'border', 'input', 'ring',
          'success', 'success-foreground', 'info', 'info-foreground', 'warning', 'warning-foreground',
          'premium', 'premium-foreground', 'surface-selected', 'surface-selected-foreground',
          'foreground-subtle', 'foreground-faint', 'sidebar', 'sidebar-foreground',
          'sidebar-item-foreground', 'sidebar-accent', 'sidebar-border', 'sidebar-panel',
          'sidebar-mobile-panel', 'sidebar-mobile-panel-foreground',
          'sidebar-mobile-panel-muted-foreground', 'sidebar-mobile-panel-accent',
          'sidebar-mobile-panel-border', 'sidebar-mobile-panel-active',
          'sidebar-mobile-panel-active-foreground', 'sidebar-mobile-panel-rail', 'overlay',
          'success-fill', 'warning-fill', 'destructive-fill', 'info-fill', 'premium-fill',
          'success-soft', 'success-soft-foreground', 'info-soft', 'info-soft-foreground',
          'warning-soft', 'warning-soft-foreground', 'destructive-soft', 'destructive-soft-foreground',
          'premium-soft', 'premium-soft-foreground'}


def parse_class(cls):
    """'text-white/70' -> ('white', 0.7); 'bg-muted' -> ('muted', 1.0)."""
    cls = cls.strip()
    m = re.match(r'(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide)-(.+)', cls)
    body = m.group(1) if m else cls
    alpha = 1.0
    if '/' in body:
        body, op = body.rsplit('/', 1)
        try:
            alpha = int(op) / 100
        except ValueError:
            alpha = 1.0
    return body, alpha


def to_hex(colorname, theme):
    if colorname in TOKENS:
        return _resolve_var(colorname, theme)
    if colorname in PALETTE:
        return PALETTE[colorname]
    return None


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _composite(fg, bg, a):
    if a >= 1:
        return fg
    fr, fgc, fb = (int(fg[i:i + 2], 16) for i in (1, 3, 5))
    br, bgc, bb = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % (round(fr * a + br * (1 - a)), round(fgc * a + bgc * (1 - a)), round(fb * a + bb * (1 - a)))


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def evaluate(text_cls, bg_cls, non_text=False):
    """Returns {theme: {'text':hex,'bg':hex,'ratio':x,'pass':bool}} + global 'ok' + 'fails'."""
    tname, ta = parse_class(text_cls)
    bname, ba = parse_class(bg_cls)
    thr = 3.0 if non_text else 4.5
    out = {}
    fails = []
    for theme in THEME_SEL:
        thex = to_hex(tname, theme)
        bhex = to_hex(bname, theme)
        if not thex or not bhex:
            out[theme] = {'text': thex, 'bg': bhex, 'ratio': None, 'pass': None,
                          'note': 'unresolvable (rgba/alias/unknown)'}
            continue
        eff = _composite(thex, bhex, ta)  # text with opacity over the background
        r = _contrast(eff, bhex)
        ok = r >= thr
        out[theme] = {'text': eff, 'bg': bhex, 'ratio': r, 'pass': ok}
        if not ok:
            fails.append(theme)
    resolved = [t for t in out.values() if t['ratio'] is not None]
    return {'text': text_cls, 'bg': bg_cls, 'threshold': thr,
            'ok': len(fails) == 0 and len(resolved) > 0, 'fails': fails, 'themes': out}


def _print(res):
    print(f"PAIR: {res['text']}  x  {res['bg']}   (threshold {res['threshold']})")
    for t, d in res['themes'].items():
        if d['ratio'] is None:
            print(f"  {t:10} —      {d.get('note', '')}")
        else:
            print(f"  {t:10} {d['ratio']:5}:1  {'PASS' if d['pass'] else 'FAIL'}   ({d['text']} over {d['bg']})")
    v = 'OK (fits)' if res['ok'] else f"does NOT fit — FAILS in: {', '.join(res['fails']) or 'unresolvable'}"
    print(f"  -> {v}\n")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--text')
    ap.add_argument('--bg')
    ap.add_argument('--non-text', action='store_true')
    ap.add_argument('--batch', action='store_true', help='reads JSON [{text,bg,non_text?}] from stdin')
    a = ap.parse_args()
    if a.batch:
        pairs = json.load(sys.stdin)
        results = [evaluate(p['text'], p['bg'], p.get('non_text', False)) for p in pairs]
        print(json.dumps(results, ensure_ascii=False))
        sys.exit(1 if any(not r['ok'] for r in results) else 0)
    if not a.text or not a.bg:
        ap.error('use --text and --bg (or --batch)')
    res = evaluate(a.text, a.bg, a.non_text)
    _print(res)
    sys.exit(0 if res['ok'] else 1)
