#!/usr/bin/env node
/**
 * Deterministic miner of repeated className combos (design token candidates).
 * v1 LITE variant: zero-dependency (no `typescript`), regex-only, without
 * structural JSX/cluster context — fallback for the v2 miner (classname-miner-v2.mjs)
 * when the `typescript` package is not available in the target project.
 *
 * Operationalizes "repeated character-string search algorithm" at the CORRECT
 * granularity for Tailwind: class-token n-grams (not char-level — char-level would split `px-3`).
 * Method = frequency-based mining of contiguous n-grams (industry standard in NLP; same
 * family as BPE/suffix-array). Deterministic: Map + stable sort.
 *
 * Ranking = GROSS SAVINGS = occurrences × (len_chars − OVERHEAD), mirroring the legal-substring-miner.
 * OVERHEAD = estimated cost of referencing the token (short name ~10 chars). Substrings whose
 * savings do not pay off the overhead do not become tokens.
 *
 * Filters n-grams with len_chars >= MIN_CHARS (default 15 = len("px-3 py-2 gap-3")).
 *
 * Usage: node .harness/lib/classname-miner.mjs [--root <dir>] [--out <dir>]
 * Output: <out>/classname-token-mining.md + .json (default <out> = docs/design-system)
 */
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, relative, resolve } from 'node:path'

const HELP_TEXT = `classname-miner.mjs — regex-only className miner (v1 lite, zero-dependency)

Usage:
  node .harness/lib/classname-miner.mjs [options]

Options:
  --root <dir>   Root scanned for .ts/.tsx (default: cwd; env HARNESS_MINER_ROOT)
  --out <dir>    Output directory for the .md/.json report
                  (default: <repo-root>/docs/design-system; env HARNESS_MINER_OUT_DIR)
  --help, -h      Show this help and exit

Without structural JSX/cluster context — prefer classname-miner-v2.mjs when
the 'typescript' package is available in the target project.
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
const MIN_TOKENS = 2        // combo needs ≥2 classes
const MAX_TOKENS = 8        // n-gram up to 8 classes
const MIN_OCCURRENCES = 3   // repeat ≥3× to be a candidate
const OVERHEAD = 10         // cost of referencing the token

// Heuristic: is the string a list of Tailwind classes? (has ≥2 tokens, and at least 1 that looks like a utility)
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

// Extracts ALL string literals (quoted with " ' `) that look like a class list.
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
    if (utilCount < 2) continue           // needs to look like classes, not prose
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
    const seen = new Set() // n-gram per document counts 1× per document so it does not inflate
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

// Filters + ranks by gross savings.
let rows = []
for (const [gram, g] of grams) {
  if (g.count < MIN_OCCURRENCES) continue
  const savings = g.count * (g.chars - OVERHEAD)
  if (savings <= 0) continue
  rows.push({ gram, occurrences: g.count, files: g.files.size, chars: g.chars, tokens: g.tokens, savings })
}
// Removes DOMINATED n-grams: if a longer n-gram has the SAME count as a shorter one contained in it,
// only the longer one stays (more specific = better token). Deterministic.
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
const md = `# className combo mining → design token candidates

> Deterministic. Method: contiguous class-token n-grams (correct Tailwind granularity), ranked by **gross savings = occurrences × (chars − ${OVERHEAD})** (mirrors the legal-substring-miner). Filters: ≥${MIN_CHARS} chars, ≥${MIN_OCCURRENCES} occurrences, dominated n-grams removed. Files scanned: ${files.length}. Candidates: ${kept.length}.

| # | combo (className substring) | occ. | files | chars | savings |
|---|---|---:|---:|---:|---:|
${top.map((r, i) => `| ${i + 1} | \`${r.gram}\` | ${r.occurrences} | ${r.files} | ${r.chars} | ${r.savings} |`).join('\n')}

> Full data: \`classname-token-mining.json\`. Savings = chars saved by extracting the combo into 1 token.
`
writeFileSync(join(outDir, 'classname-token-mining.md'), md)

console.log('=== CLASSNAME TOKEN MINER (v1 lite) ===')
console.log('Scanned root:', WEB_ROOT)
console.log('Files:', files.length, '| candidates (≥%d occ, ≥%d chars):', MIN_OCCURRENCES, MIN_CHARS, kept.length)
console.log('TOP 25 by gross savings:')
for (const r of top.slice(0, 25)) console.log(`  ${String(r.savings).padStart(5)}  ×${String(r.occurrences).padStart(3)}  ${r.files}files  "${r.gram}"`)
console.log('Output:', `${relative(REPO_ROOT, outDir) || '.'}/classname-token-mining.md + .json`)
