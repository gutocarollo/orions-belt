#!/usr/bin/env node
/**
 * Minerador determinístico de combos de className repetidos (candidatos a design token).
 * Variante v1 LITE: zero-dependência (sem `typescript`), regex-only, sem contexto
 * estrutural de JSX/clusters — fallback do miner v2 (classname-miner-v2.mjs) quando
 * o pacote `typescript` não está disponível no projeto-alvo.
 *
 * Operacionaliza "algoritmo de busca por cadeias de caracteres repetidos" na granularidade
 * CORRETA para Tailwind: class-token n-grams (não char-level — char-level partiria `px-3`).
 * Método = mineração de n-gramas contíguos por frequência (padrão de mercado em NLP; mesma
 * família do BPE/suffix-array). Determinístico: Map + sort estável.
 *
 * Ranking = ECONOMIA BRUTA = ocorrências × (len_chars − OVERHEAD), espelhando o legal-substring-miner.
 * OVERHEAD = custo estimado de referenciar o token (nome curto ~10 chars). Substrings cuja
 * economia não paga o overhead não viram token.
 *
 * Filtra n-grams com len_chars >= MIN_CHARS (default 15 = len("px-3 py-2 gap-3")).
 *
 * Uso: node .harness/lib/classname-miner.mjs [--root <dir>] [--out <dir>]
 * Saída: <out>/classname-token-mining.md + .json (default <out> = docs/design-system)
 */
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, relative, resolve } from 'node:path'

const HELP_TEXT = `classname-miner.mjs — minerador regex-only de className (v1 lite, zero-dependencia)

Uso:
  node .harness/lib/classname-miner.mjs [opcoes]

Opcoes:
  --root <dir>   Raiz varrida em busca de .ts/.tsx (default: cwd; env HARNESS_MINER_ROOT)
  --out <dir>    Diretorio de saida do relatorio .md/.json
                  (default: <repo-root>/docs/design-system; env HARNESS_MINER_OUT_DIR)
  --help, -h      Mostra esta ajuda e sai

Sem contexto estrutural de JSX/clusters — prefira classname-miner-v2.mjs quando
o pacote 'typescript' estiver disponivel no projeto-alvo.
`

function argValue(flag) {
  const idx = process.argv.indexOf(flag)
  return idx !== -1 ? process.argv[idx + 1] : undefined
}

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log(HELP_TEXT)
  process.exit(0)
}

function detectRepoRoot(root) {
  try {
    return execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return root
  }
}

const WEB_ROOT = resolve(argValue('--root') || process.env.HARNESS_MINER_ROOT || process.cwd())
const REPO_ROOT = detectRepoRoot(WEB_ROOT)
const SKIP = new Set(['node_modules', '.next', '.git', 'dist', 'build', 'coverage', 'test-results', 'playwright-report', '.turbo'])

const MIN_CHARS = 15        // = len("px-3 py-2 gap-3")
const MIN_TOKENS = 2        // combo precisa ≥2 classes
const MAX_TOKENS = 8        // n-gram até 8 classes
const MIN_OCCURRENCES = 3   // repetir ≥3× p/ ser candidato
const OVERHEAD = 10         // custo de referenciar o token

// Heurística: a string é uma lista de classes Tailwind? (tem ≥2 tokens, e ao menos 1 com cara de utility)
const UTIL = /^(?:-?(?:[a-z]+:)*)(?:flex|grid|items-|justify-|gap-|space-|p[xytrbl]?-|m[xytrbl]?-|w-|h-|min-|max-|text-|font-|bg-|border|rounded|shadow|ring|outline|absolute|relative|fixed|sticky|inline|block|hidden|overflow|transition|duration|ease-|opacity|cursor|z-|top-|left-|right-|bottom-|translate|rotate|scale|truncate|whitespace|leading|tracking|divide|backdrop|aspect|object-|self-|order-|col-|row-|basis-|grow|shrink|antialiased)/

function walk(dir, acc = []) {
  let ents; try { ents = readdirSync(dir, { withFileTypes: true }) } catch { return acc }
  for (const e of ents) {
    if (e.name.startsWith('.') || SKIP.has(e.name)) continue
    const full = join(dir, e.name)
    if (e.isDirectory()) walk(full, acc)
    else if (/\.tsx?$/.test(e.name) && !e.name.endsWith('.d.ts')) acc.push(full)
  }
  return acc
}

// Extrai TODAS as string-literais (entre aspas " ' `) que parecem lista de classes.
function extractClassStrings(src) {
  const out = []
  const re = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/g
  let m
  while ((m = re.exec(src)) !== null) {
    const s = m[2].trim()
    if (!s || s.includes('${') || s.includes('\n')) continue
    const toks = s.split(/\s+/).filter(Boolean)
    if (toks.length < MIN_TOKENS) continue
    const utilCount = toks.filter(t => UTIL.test(t)).length
    if (utilCount < 2) continue           // precisa parecer classes, não prosa
    out.push(toks)
  }
  return out
}

const files = walk(WEB_ROOT)
// ngram -> { count, files:Set, tokens }
const grams = new Map()
for (const f of files) {
  const rel = relative(REPO_ROOT, f).split('\\').join('/')
  const src = readFileSync(f, 'utf8')
  for (const toks of extractClassStrings(src)) {
    const seen = new Set() // n-gram por documento conta 1× por documento p/ não inflar
    for (let n = MIN_TOKENS; n <= Math.min(MAX_TOKENS, toks.length); n++) {
      for (let i = 0; i + n <= toks.length; i++) {
        const gram = toks.slice(i, i + n).join(' ')
        if (gram.length < MIN_CHARS) continue
        const key = gram
        let g = grams.get(key)
        if (!g) { g = { count: 0, files: new Set(), tokens: n, chars: gram.length }; grams.set(key, g) }
        g.count++
        g.files.add(rel)
        seen.add(key)
      }
    }
  }
}

// Filtra + ranqueia por economia bruta.
let rows = []
for (const [gram, g] of grams) {
  if (g.count < MIN_OCCURRENCES) continue
  const savings = g.count * (g.chars - OVERHEAD)
  if (savings <= 0) continue
  rows.push({ gram, occurrences: g.count, files: g.files.size, chars: g.chars, tokens: g.tokens, savings })
}
// Remove n-grams DOMINADOS: se um n-gram maior tem a MESMA contagem de um menor contido nele,
// fica só o maior (mais específico = melhor token). Determinístico.
rows.sort((a, b) => b.chars - a.chars)
const kept = []
for (const r of rows) {
  const dominated = kept.some(k => k.occurrences === r.occurrences && k.gram.includes(r.gram))
  if (!dominated) kept.push(r)
}
kept.sort((a, b) => b.savings - a.savings || b.occurrences - a.occurrences)

const outDir = resolve(argValue('--out') || process.env.HARNESS_MINER_OUT_DIR || join(REPO_ROOT, 'docs', 'design-system'))
mkdirSync(outDir, { recursive: true })
writeFileSync(join(outDir, 'classname-token-mining.json'), JSON.stringify({
  params: { MIN_CHARS, MIN_TOKENS, MAX_TOKENS, MIN_OCCURRENCES, OVERHEAD },
  scanned: files.length, candidates: kept.length, rows: kept,
}, null, 2))

const top = kept.slice(0, 60)
const md = `# Mineração de combos de className → candidatos a design token

> Determinístico. Método: n-gramas contíguos de class-tokens (granularidade Tailwind correta), ranqueado por **economia bruta = ocorrências × (chars − ${OVERHEAD})** (espelha o legal-substring-miner). Filtros: ≥${MIN_CHARS} chars, ≥${MIN_OCCURRENCES} ocorrências, n-grams dominados removidos. Arquivos varridos: ${files.length}. Candidatos: ${kept.length}.

| # | combo (substring de className) | ocorr. | arq. | chars | economia |
|---|---|---:|---:|---:|---:|
${top.map((r, i) => `| ${i + 1} | \`${r.gram}\` | ${r.occurrences} | ${r.files} | ${r.chars} | ${r.savings} |`).join('\n')}

> Dados completos: \`classname-token-mining.json\`. Economia = chars poupados ao extrair o combo para 1 token.
`
writeFileSync(join(outDir, 'classname-token-mining.md'), md)

console.log('=== CLASSNAME TOKEN MINER (v1 lite) ===')
console.log('Raiz varrida:', WEB_ROOT)
console.log('Arquivos:', files.length, '| candidatos (≥%d ocorr, ≥%d chars):', MIN_OCCURRENCES, MIN_CHARS, kept.length)
console.log('TOP 25 por economia bruta:')
for (const r of top.slice(0, 25)) console.log(`  ${String(r.savings).padStart(5)}  ×${String(r.occurrences).padStart(3)}  ${r.files}arq  "${r.gram}"`)
console.log('Saída:', `${relative(REPO_ROOT, outDir) || '.'}/classname-token-mining.md + .json`)
