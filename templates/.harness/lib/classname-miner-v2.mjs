#!/usr/bin/env node
/**
 * Minerador AST/JSX de className para reabstracao segura.
 *
 * V2 mantem o miner v1 intacto e adiciona contexto estrutural: ocorrencias,
 * ancestrais JSX, raiz interativa, roles de siblings e clusters semanticos.
 *
 * Generico por design: nenhum path/DSN/alias de projeto especifico
 * hardcoded. Raiz varrida, diretorio de saida e tags interativas extras
 * sao configuraveis via flag ou env var (--help lista tudo); os
 * path-aliases (@components/*, @/* etc.) sao lidos do tsconfig.json/
 * jsconfig.json do projeto-alvo via TypeScript Compiler API, nunca de uma
 * lista fixa.
 *
 * Uso: node .harness/lib/classname-miner-v2.mjs [--root <dir>] [--out <dir>]
 *      [--interactive-tags <csv>] [--emit-full <dir>] [--emit-json] [--self-test]
 */
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs'
import { createRequire } from 'node:module'
import {
  dirname,
  join,
  relative,
  resolve,
} from 'node:path'
import { pathToFileURL } from 'node:url'

const HELP_TEXT = `classname-miner-v2.mjs — minerador AST/JSX de className (TypeScript Compiler API)

Uso:
  node .harness/lib/classname-miner-v2.mjs [opcoes]

Opcoes:
  --root <dir>              Raiz varrida em busca de .ts/.tsx (default: cwd; env HARNESS_MINER_ROOT)
  --out <dir>                Diretorio de saida do relatorio .md/.json
                              (default: <repo-root>/docs/design-system/sources; env HARNESS_MINER_OUT_DIR)
  --interactive-tags <csv>   Tags JSX extras tratadas como raiz interativa, alem do
                              default a,button,Link (env HARNESS_MINER_INTERACTIVE_TAGS)
  --emit-full <dir>          Grava dataset NDJSON COMPLETO (run/occ/ent/ngram/cluster) em <dir>
  --emit-json                Tambem grava o JSON truncado (arqueologia/backup manual)
  --self-test                Valida a forma do schema de saida e sai
  --help, -h                  Mostra esta ajuda e sai

Path-aliases (@components/*, @/* etc.) sao lidos do tsconfig.json/jsconfig.json
de --root — sem arquivo de config, resolucao de alias fica vazia (resolucao
relativa continua funcionando). Nenhum DSN de banco de dados e usado por este
script; a ingestao relacional opcional fica em ferramenta separada.
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

// Import dinamico (nao estatico) de propósito, resolvido a partir de --root
// (nao da localizacao deste arquivo): este script mora em .harness/lib/, um
// IRMAO do app escaneado (nao um descendente) — um import bare estatico
// 'typescript' resolveria node_modules a partir de .harness/lib/ para cima,
// nunca encontrando o 'typescript' que vive em <root>/node_modules (comum em
// monorepo, ex. apps/web/node_modules). createRequire ancorado em --root
// replica o algoritmo real de resolucao do Node a partir do app-alvo. Isso
// tambem adia a resolucao para depois do --help acima — projeto-alvo sem
// 'typescript' instalado ainda consegue ver a ajuda.
async function loadTypeScript(root) {
  const req = createRequire(join(root, 'package.json'))
  const resolvedPath = req.resolve('typescript')
  const mod = await import(pathToFileURL(resolvedPath).href)
  return mod.default ?? mod
}

let ts
try {
  ts = await loadTypeScript(WEB_ROOT)
} catch {
  console.error(
    `ERRO: pacote 'typescript' nao encontrado a partir de --root (${WEB_ROOT}).\n` +
    "Instale-o como devDependency nesse diretorio, ou use o fallback zero-dependencia:\n" +
    '  node .harness/lib/classname-miner.mjs --root <dir>'
  )
  process.exit(1)
}
const OUT_DIR = resolve(
  argValue('--out') || process.env.HARNESS_MINER_OUT_DIR || join(REPO_ROOT, 'docs', 'design-system', 'sources')
)
const OUT_JSON = join(OUT_DIR, 'classname-token-mining-v2.json')
const OUT_MD = join(OUT_DIR, 'classname-token-mining-v2.md')

const SKIP = new Set([
  'node_modules',
  '.next',
  '.git',
  'dist',
  'build',
  'coverage',
  'test-results',
  'playwright-report',
  '.turbo',
])

const MIN_CHARS = 15
const MIN_TOKENS = 2
const MAX_TOKENS = 8
const MIN_OCCURRENCES = 3
const OVERHEAD = 10

const CLASSY =
  /^(?:!?-?(?:[a-z0-9-]+:)*)(?:flex|grid|items-|justify-|content-|gap-|space-|p[xytrbl]?-|m[xytrbl]?-|w-|h-|min-|max-|text-|font-|bg-|border|rounded|shadow|ring|outline|absolute|relative|fixed|sticky|inline|block|hidden|overflow|transition|duration|ease-|opacity|cursor|z-|top-|left-|right-|bottom-|translate|rotate|scale|truncate|whitespace|leading|tracking|divide|backdrop|aspect|object-|self-|order-|col-|row-|basis-|grow|shrink|antialiased|lh-)/

function loadInteractiveTags() {
  const DEFAULT_TAGS = ['a', 'button', 'Link']
  const csv = argValue('--interactive-tags') || process.env.HARNESS_MINER_INTERACTIVE_TAGS || ''
  const extra = csv.split(',').map((tag) => tag.trim()).filter(Boolean)
  return new Set([...DEFAULT_TAGS, ...extra])
}
const INTERACTIVE_TAGS = loadInteractiveTags()

const ICON_SOURCES = new Set(['lucide-react', '@radix-ui/react-icons'])

// Le @alias/* de tsconfig.json/jsconfig.json (com `extends`, via TS Compiler API)
// em vez de uma lista fixa — fail-open: sem config, retorna [] (so resolucao
// relativa funciona; nenhum crash).
function loadTsPathAliases(root) {
  const configNames = ['tsconfig.json', 'jsconfig.json']
  let configPath
  for (const name of configNames) {
    const candidate = join(root, name)
    if (existsSync(candidate)) {
      configPath = candidate
      break
    }
  }
  if (!configPath) return []
  try {
    const readResult = ts.readConfigFile(configPath, ts.sys.readFile)
    if (readResult.error) return []
    const parsed = ts.parseJsonConfigFileContent(readResult.config, ts.sys, dirname(configPath))
    const paths = parsed.options.paths || {}
    const baseUrl = parsed.options.baseUrl ? resolve(dirname(configPath), parsed.options.baseUrl) : root
    const aliases = []
    for (const [key, targets] of Object.entries(paths)) {
      if (!Array.isArray(targets) || targets.length === 0) continue
      const prefix = key.replace(/\*$/, '')
      const targetRel = targets[0].replace(/\*$/, '')
      aliases.push([prefix, join(baseUrl, targetRel)])
    }
    // Prefixo mais longo (mais especifico) primeiro, senao "@/" (catch-all)
    // casaria antes de "@components/" no primeiro .find().
    return aliases.sort((a, b) => b[0].length - a[0].length)
  } catch {
    return []
  }
}
const TS_PATH_ALIASES = loadTsPathAliases(WEB_ROOT)

function hash(value) {
  return createHash('sha256').update(value).digest('hex').slice(0, 16)
}

function stableEntries(map) {
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
}

function walk(dir, acc = []) {
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return acc
  }
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name.startsWith('.') || SKIP.has(entry.name)) continue
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, acc)
    else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith('.d.ts')) acc.push(full)
  }
  return acc.sort()
}

function relPath(absPath) {
  return relative(REPO_ROOT, absPath).split('\\').join('/')
}

function scriptKind(file) {
  return file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
}

function pos(sourceFile, node) {
  const start = node.getStart(sourceFile)
  const lc = sourceFile.getLineAndCharacterOfPosition(start)
  return { line: lc.line + 1, column: lc.character + 1, offset: start }
}

function textOf(node, sourceFile, max = 120) {
  const text = node.getText(sourceFile).replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, max)}...` : text
}

function tokensOf(value) {
  return value.split(/\s+/).map((token) => token.trim()).filter(Boolean)
}

function isClassLike(value) {
  const tokens = tokensOf(value)
  if (tokens.length === 0) return false
  const utilityCount = tokens.filter((token) => CLASSY.test(token)).length
  return utilityCount > 0 && (tokens.length > 1 || tokens.some((token) => token.startsWith('lh-')))
}

function literalValue(node) {
  if (!node) return undefined
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  if (ts.isNumericLiteral(node)) return Number(node.text)
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false
  return undefined
}

function getTagName(node, sourceFile) {
  if (!node) return undefined
  if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
    return node.tagName.getText(sourceFile)
  }
  if (ts.isJsxElement(node)) return node.openingElement.tagName.getText(sourceFile)
  return undefined
}

function jsxOpeningFor(node) {
  if (!node) return undefined
  if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) return node
  if (ts.isJsxElement(node)) return node.openingElement
  return undefined
}

function owningJsxElement(opening) {
  if (!opening) return undefined
  if (ts.isJsxSelfClosingElement(opening)) return opening
  if (opening.parent && ts.isJsxElement(opening.parent)) return opening.parent
  return opening
}

function jsxAttributes(opening) {
  return opening?.attributes?.properties?.filter(ts.isJsxAttribute) ?? []
}

function attrByName(opening, name) {
  return jsxAttributes(opening).find((attr) => attr.name.getText() === name)
}

function attrValue(attr, ctx) {
  if (!attr?.initializer) return true
  if (ts.isStringLiteral(attr.initializer)) return attr.initializer.text
  if (ts.isJsxExpression(attr.initializer) && attr.initializer.expression) {
    const value = resolveExpressionValue(attr.initializer.expression, ctx)
    if (value !== undefined) return value
    return textOf(attr.initializer.expression, ctx.sourceFile)
  }
  return textOf(attr.initializer, ctx.sourceFile)
}

function collectImports(sourceFile, absPath) {
  const imports = new Map()
  const importSources = new Map()
  sourceFile.forEachChild((node) => {
    if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) return
    const source = node.moduleSpecifier.text
    const clause = node.importClause
    if (!clause) return
    if (clause.name) {
      imports.set(clause.name.text, { imported: 'default', source, sourceAbs: resolveImport(absPath, source) })
      importSources.set(clause.name.text, source)
    }
    const named = clause.namedBindings
    if (named && ts.isNamedImports(named)) {
      for (const spec of named.elements) {
        const local = spec.name.text
        const imported = spec.propertyName?.text ?? spec.name.text
        imports.set(local, { imported, source, sourceAbs: resolveImport(absPath, source) })
        importSources.set(local, source)
      }
    }
  })
  return { imports, importSources }
}

function resolveImport(absPath, specifier) {
  let base
  if (specifier.startsWith('.')) {
    base = resolve(dirname(absPath), specifier)
  } else {
    const alias = TS_PATH_ALIASES.find(([prefix]) => specifier.startsWith(prefix))
    if (!alias) return undefined
    base = join(alias[1], specifier.slice(alias[0].length))
  }
  const candidates = [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, 'index.ts'),
    join(base, 'index.tsx'),
  ]
  return candidates.find((candidate) => existsSync(candidate))
}

function collectConstValues(sourceFile) {
  const local = new Map()
  const exported = new Map()
  function visit(node) {
    if (ts.isVariableStatement(node)) {
      const isExported = node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) ?? false
      for (const declaration of node.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue
        const value = literalValue(declaration.initializer)
        if (value === undefined) continue
        local.set(declaration.name.text, value)
        if (isExported) exported.set(declaration.name.text, value)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return { local, exported }
}

function resolveExpressionValue(node, ctx) {
  const direct = literalValue(node)
  if (direct !== undefined) return direct
  if (ts.isIdentifier(node)) {
    if (ctx.localConsts.has(node.text)) return ctx.localConsts.get(node.text)
    const imported = ctx.imports.get(node.text)
    if (imported?.sourceAbs) {
      return ctx.exportedConstValues.get(`${imported.sourceAbs}:${imported.imported}`)
    }
  }
  return undefined
}

function expressionKind(node, ctx) {
  if (!node) return 'unknown'
  if (ts.isStringLiteral(node)) return 'literal'
  if (ts.isNoSubstitutionTemplateLiteral(node)) return 'template-literal-static'
  if (ts.isIdentifier(node)) return `identifier:${node.text}`
  if (ts.isCallExpression(node)) return `call:${node.expression.getText(ctx.sourceFile)}`
  if (ts.isConditionalExpression(node)) return 'conditional'
  if (ts.isJsxExpression(node)) return 'jsx-expression'
  return ts.SyntaxKind[node.kind] ?? 'unknown'
}

function extractClassValues(node, ctx, sourceExpressionKind, out = []) {
  const resolved = resolveExpressionValue(node, ctx)
  if (typeof resolved === 'string' && isClassLike(resolved)) {
    out.push({ value: resolved, node, sourceExpressionKind })
    return out
  }

  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    if (isClassLike(node.text)) out.push({ value: node.text, node, sourceExpressionKind })
    return out
  }

  if (ts.isTemplateExpression(node)) {
    const parts = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    for (const part of parts) {
      if (isClassLike(part)) out.push({ value: part, node, sourceExpressionKind: `${sourceExpressionKind}:template-quasi` })
    }
    for (const span of node.templateSpans) extractClassValues(span.expression, ctx, `${sourceExpressionKind}:template-expression`, out)
    return out
  }

  if (ts.isJsxExpression(node) && node.expression) {
    return extractClassValues(node.expression, ctx, expressionKind(node.expression, ctx), out)
  }

  if (ts.isCallExpression(node)) {
    const callee = node.expression.getText(ctx.sourceFile)
    for (const arg of node.arguments) extractClassValues(arg, ctx, `call:${callee}`, out)
    return out
  }

  if (ts.isConditionalExpression(node)) {
    extractClassValues(node.whenTrue, ctx, `${sourceExpressionKind}:whenTrue`, out)
    extractClassValues(node.whenFalse, ctx, `${sourceExpressionKind}:whenFalse`, out)
    return out
  }

  if (ts.isArrayLiteralExpression(node)) {
    for (const element of node.elements) extractClassValues(element, ctx, `${sourceExpressionKind}:array`, out)
    return out
  }

  if (ts.isObjectLiteralExpression(node)) {
    for (const prop of node.properties) {
      if (ts.isPropertyAssignment(prop)) extractClassValues(prop.initializer, ctx, `${sourceExpressionKind}:object`, out)
    }
    return out
  }

  if (ts.isParenthesizedExpression(node)) {
    return extractClassValues(node.expression, ctx, sourceExpressionKind, out)
  }

  if (ts.isBinaryExpression(node)) {
    extractClassValues(node.left, ctx, `${sourceExpressionKind}:binary-left`, out)
    extractClassValues(node.right, ctx, `${sourceExpressionKind}:binary-right`, out)
    return out
  }

  ts.forEachChild(node, (child) => extractClassValues(child, ctx, sourceExpressionKind, out))
  return out
}

function nearestComponentOwner(node, sourceFile) {
  let current = node
  while (current) {
    if (ts.isFunctionDeclaration(current) && current.name) return current.name.text
    if (ts.isClassDeclaration(current) && current.name) return current.name.text
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name)) return current.name.text
    if (ts.isMethodDeclaration(current) && current.name) return current.name.getText(sourceFile)
    current = current.parent
  }
  return 'module'
}

function nearestJsxOpening(node) {
  let current = node
  while (current) {
    if (ts.isJsxOpeningElement(current) || ts.isJsxSelfClosingElement(current)) return current
    current = current.parent
  }
  return undefined
}

function ancestorChain(node, sourceFile, limit = 5) {
  const chain = []
  let current = node
  while (current && chain.length < limit) {
    if (ts.isJsxElement(current)) {
      chain.push(current.openingElement.tagName.getText(sourceFile))
    } else if (ts.isJsxSelfClosingElement(current)) {
      chain.push(current.tagName.getText(sourceFile))
    }
    current = current.parent
  }
  return chain
}

function propsSummary(opening, ctx) {
  if (!opening) return {}
  const props = {}
  for (const name of [
    'href',
    'role',
    'type',
    'name',
    'id',
    'title',
    'placeholder',
    'aria-current',
    'aria-label',
    'disabled',
    'asChild',
    'onClick',
    'onChange',
    'onMouseDown',
    'inputMode',
    'rows',
  ]) {
    const attr = attrByName(opening, name)
    if (attr) props[name] = attrValue(attr, ctx)
  }
  return props
}

function hasEventOrHref(opening) {
  return Boolean(attrByName(opening, 'href') || attrByName(opening, 'onClick'))
}

function findInteractiveRoot(opening, ctx) {
  let current = owningJsxElement(opening)
  while (current) {
    const currentOpening = jsxOpeningFor(current)
    const tag = getTagName(currentOpening, ctx.sourceFile)
    if (tag && (INTERACTIVE_TAGS.has(tag) || hasEventOrHref(currentOpening))) {
      const position = pos(ctx.sourceFile, currentOpening)
      return {
        id: `${ctx.rel}:L${position.line}:${position.column}:${tag}`,
        tag,
        line: position.line,
        column: position.column,
        props: propsSummary(currentOpening, ctx),
      }
    }
    current = current.parent
  }
  return undefined
}

function routeInfo(rel) {
  const parts = rel.split('/')
  const appIndex = parts.indexOf('app')
  const segments = appIndex >= 0 ? parts.slice(appIndex + 1, -1) : parts.slice(0, -1)
  let area = 'unknown'
  if (rel.includes('/Dashboard/')) area = 'dashboard-components'
  else if (segments.includes('dash')) area = 'dash'
  else if (segments.includes('admin')) area = 'admin'
  else if (segments.includes('auth')) area = 'auth'
  else if (segments.includes('orgs')) area = 'public-org'
  else if (rel.includes('/components/ui/')) area = 'ui-primitive'
  else if (rel.includes('/components/')) area = 'component-library'
  return {
    area,
    segments,
    dynamicParams: segments.filter((segment) => segment.startsWith('[') && segment.endsWith(']')),
  }
}

function surfaceRole(rel, tag, tokens, ancestorTags, props) {
  const tokenSet = new Set(tokens)
  if (rel.includes('/Dashboard/Menus/') || tokens.some((token) => token.includes('sidebar-'))) {
    return 'sidebar-nav-item'
  }
  if (ancestorTags.some((item) => /Dropdown|HoverMenu|Popover|Command/.test(item))) return 'menu-or-popover-item'
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || props?.role === 'textbox') return 'input'
  if (tokenSet.has('fixed') && (tokenSet.has('bottom-0') || tokens.some((token) => token.startsWith('bottom-')))) return 'fixed-mobile-bar'
  if (tokenSet.has('bg-card') || tokens.some((token) => token.includes('rounded-xl'))) return 'card-or-panel'
  if (INTERACTIVE_TAGS.has(tag) || props?.onClick || props?.href) return 'interactive-control'
  return 'structural'
}

function tokenFamily(token) {
  const base = token.split(':').pop() ?? token
  const normalized = base.replace(/^!?-?/, '')
  if (normalized.startsWith('lh-')) return 'lh'
  if (normalized.startsWith('text-')) return 'text'
  if (normalized.startsWith('bg-')) return 'bg'
  if (normalized.startsWith('border')) return 'border'
  if (normalized.startsWith('rounded')) return 'rounded'
  if (normalized.startsWith('focus')) return 'focus'
  if (/^(p|px|py|pt|pr|pb|pl)-/.test(normalized)) return 'padding'
  if (/^(m|mx|my|mt|mr|mb|ml)-/.test(normalized)) return 'margin'
  if (/^(w|h|min-w|min-h|max-w|max-h)-/.test(normalized)) return 'size'
  if (/^(flex|grid|items-|justify-|gap-|space-)/.test(normalized)) return 'layout'
  if (/^(shadow|ring|outline)/.test(normalized)) return 'focus-or-shadow'
  if (/^(transition|duration|ease-|animate-)/.test(normalized)) return 'motion'
  if (/^(absolute|relative|fixed|sticky|z-|top-|right-|bottom-|left-)/.test(normalized)) return 'position'
  return normalized.split('-')[0] || 'unknown'
}

function variantPrefixes(tokens) {
  return [...new Set(tokens.flatMap((token) => {
    const parts = token.split(':')
    return parts.length > 1 ? parts.slice(0, -1) : []
  }))].sort()
}

function normalizedText(value) {
  return String(value ?? '').toLowerCase()
}

function featureDomain(rel) {
  const parts = rel.split('/')
  const dashIndex = parts.indexOf('dash')
  if (dashIndex >= 0 && parts[dashIndex + 1]) return parts[dashIndex + 1]
  const componentIndex = parts.indexOf('components')
  if (componentIndex >= 0 && parts[componentIndex + 1]) return parts[componentIndex + 1]
  const appIndex = parts.indexOf('app')
  if (appIndex >= 0 && parts[appIndex + 1]) return parts[appIndex + 1]
  return 'unknown'
}

function renderContext(rel, ancestorTags, surface) {
  if (surface === 'sidebar-nav-item' || rel.includes('/Dashboard/Menus/')) return 'sidebar'
  if (rel.includes('/Objects/Editor/') || rel.includes('/Dashboard/Boards/Extensions/')) return 'editor'
  if (rel.includes('/Objects/Activities/') || rel.includes('/Podcasts/') || rel.includes('/Podcast/')) return 'media'
  if (rel.includes('/Objects/Modals/') || ancestorTags.some((item) => /Dialog|Modal/.test(item))) return 'modal'
  if (ancestorTags.some((item) => /Dropdown|HoverMenu|Popover|Command/.test(item))) return 'overlay-menu'
  if (rel.includes('/dash/')) return 'dashboard-page'
  if (rel.includes('/admin/')) return 'admin-page'
  if (rel.includes('/auth/')) return 'auth-page'
  if (rel.includes('/components/ui/')) return 'ui-primitive'
  return 'component'
}

function inputIntent(rel, tag, props, context) {
  if (!(tag === 'input' || tag === 'textarea' || tag === 'select' || props?.role === 'textbox')) return undefined
  const haystack = [
    props?.type,
    props?.name,
    props?.id,
    props?.placeholder,
    props?.['aria-label'],
    props?.title,
    rel,
  ].map(normalizedText).join(' ')
  if (haystack.includes('search') || haystack.includes('buscar') || haystack.includes('pesquisar')) return 'search'
  if (haystack.includes('filter') || haystack.includes('filtro')) return 'filter'
  if (context === 'admin-page' || rel.includes('/components/Admin/')) return 'admin-console'
  if (rel.includes('/TaskEditor/')) return 'task-editor'
  if (context === 'modal') return 'modal-field'
  if (/\/dash\/(broadcasts|certificate-templates|certificates|gamification|goals|live-sessions|positions|reports|rewards|scheduled-reports|security-policy|taxonomy)\//.test(rel)) return 'dashboard-crud'
  return 'form-field'
}

function operationKind(tag, props, rel, roles, tokens) {
  const haystack = [
    tag,
    props?.href,
    props?.title,
    props?.['aria-label'],
    props?.onClick,
    props?.onMouseDown,
    rel,
    roles.map((role) => role.tag).join(' '),
    tokens.join(' '),
  ].map(normalizedText).join(' ')
  if (props?.href) return 'navigation'
  if (haystack.includes('delete') || haystack.includes('remove') || haystack.includes('trash') || haystack.includes('destructive')) return 'delete'
  if (haystack.includes('create') || haystack.includes('add') || haystack.includes('plus') || haystack.includes('new')) return 'create'
  if (haystack.includes('edit') || haystack.includes('update') || haystack.includes('save') || haystack.includes('pencil')) return 'update'
  if (haystack.includes('search')) return 'search'
  if (haystack.includes('play') || haystack.includes('pause') || haystack.includes('audio') || haystack.includes('video')) return 'media'
  if (haystack.includes('open') || haystack.includes('close') || haystack.includes('toggle') || haystack.includes('x')) return 'toggle'
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return 'input'
  return 'unknown'
}

function interactionRisk(surface, context, operation, props) {
  if (props?.onMouseDown || context === 'editor' || context === 'media') return 'high'
  if (surface === 'sidebar-nav-item' || context === 'overlay-menu' || operation === 'delete') return 'medium'
  if (surface === 'input' || surface === 'card-or-panel') return 'low'
  return 'medium'
}

function classAttrValues(opening, ctx) {
  const attr = attrByName(opening, 'className') ?? attrByName(opening, 'class')
  if (!attr?.initializer) return []
  return extractClassValues(attr.initializer, ctx, `jsx-attr:${expressionKind(attr.initializer, ctx)}`)
}

function numericProp(opening, name, ctx) {
  const attr = attrByName(opening, name)
  if (!attr?.initializer) return undefined
  if (ts.isStringLiteral(attr.initializer)) return Number(attr.initializer.text)
  if (ts.isJsxExpression(attr.initializer) && attr.initializer.expression) {
    const value = resolveExpressionValue(attr.initializer.expression, ctx)
    return typeof value === 'number' ? value : undefined
  }
  return undefined
}

function importedSourceFor(tag, ctx) {
  return ctx.importSources.get(tag)
}

function isIconTag(tag, ctx) {
  const source = importedSourceFor(tag, ctx)
  if (source && ICON_SOURCES.has(source)) return true
  return /^[A-Z][A-Za-z0-9]*(Icon|Open|Closed|User|Users|House|Home|Book|File|Chart|Settings|Globe|Help|Chevron|Plus|Search|Menu|X|Check|Box|Dollar|Headphones|Panel|Messages|Circle)/.test(tag)
}

function roleForElement(opening, ctx) {
  const tag = getTagName(opening, ctx.sourceFile)
  if (!tag) return undefined
  const classValues = classAttrValues(opening, ctx)
  const tokens = classValues.flatMap((item) => tokensOf(item.value))
  const tokenSet = new Set(tokens)
  if (tag.includes('Chevron')) return 'chevron'
  if (tag === 'UserAvatar' || tag.includes('Avatar')) return 'avatar'
  if (tag.includes('Badge')) return 'badge'
  if (tokenSet.has('absolute') && (tokens.some((token) => token.startsWith('left-')) || tokens.some((token) => token.startsWith('bg-sidebar-foreground')))) return 'activeRail'
  if ((tag === 'span' || tag === 'p') && (tokenSet.has('truncate') || tokenSet.has('text-left') || tokenSet.has('lh-sidebar-item-label') || tokenSet.has('lh-sidebar-item-label-fill'))) return 'label'
  if (isIconTag(tag, ctx)) return 'icon'
  return undefined
}

function collectRoleElements(rootOpening, ctx) {
  const root = owningJsxElement(rootOpening)
  if (!root || ts.isJsxSelfClosingElement(root)) return []
  const roles = []
  function visit(node) {
    const opening = jsxOpeningFor(node)
    if (opening && opening !== rootOpening) {
      const role = roleForElement(opening, ctx)
      if (role) {
        const tag = getTagName(opening, ctx.sourceFile)
        const location = pos(ctx.sourceFile, opening)
        roles.push({
          role,
          tag,
          line: location.line,
          importedFrom: importedSourceFor(tag, ctx),
          size: numericProp(opening, 'size', ctx),
        })
      }
    }
    ts.forEachChild(node, visit)
  }
  ts.forEachChild(root, visit)
  const deduped = new Map()
  for (const role of roles) {
    const key = `${role.role}:${role.tag}:L${role.line}`
    deduped.set(key, role)
  }
  return [...deduped.values()].sort((a, b) => a.line - b.line || a.role.localeCompare(b.role))
}

function ngrams(tokens) {
  const grams = []
  for (let n = MIN_TOKENS; n <= Math.min(MAX_TOKENS, tokens.length); n++) {
    for (let i = 0; i + n <= tokens.length; i++) {
      const gram = tokens.slice(i, i + n).join(' ')
      if (gram.length >= MIN_CHARS) grams.push(gram)
    }
  }
  return grams
}

function clusterDecision(cluster) {
  if (cluster.surfaceRole === 'sidebar-nav-item') return 'component_contract_candidate'
  if (cluster.surfaceRole === 'input') return 'component_contract_candidate'
  if (cluster.surfaceRole === 'card-or-panel') return 'style_token_candidate'
  if (cluster.surfaceRole === 'fixed-mobile-bar') return 'hook_or_component_candidate'
  if (cluster.surfaceRole === 'structural') return 'review_required'
  return 'review_required'
}

function antiMergeReasons(cluster) {
  const reasons = []
  if (cluster.distinctRouteAreas.length > 1) reasons.push('multiple-route-areas')
  if (cluster.uniqueInteractiveTags.length > 1) reasons.push('multiple-interactive-tags')
  if (cluster.surfaceRole === 'structural') reasons.push('generic-structural-classes')
  if (cluster.roles.length === 0) reasons.push('no-semantic-child-roles')
  return reasons
}

function clusterHeterogeneity(cluster) {
  return {
    routeAreas: cluster.distinctRouteAreas.length,
    interactiveTags: cluster.uniqueInteractiveTags.length,
    classHashes: cluster.classHashCount,
    roles: cluster.roles.length,
    iconSizes: cluster.iconSizes.length,
    renderContexts: cluster.renderContexts.length,
    featureDomains: cluster.featureDomains.length,
    inputIntents: cluster.inputIntents.length,
    operationKinds: cluster.operationKinds.length,
    interactionRisks: cluster.interactionRisks.length,
  }
}

function recommendedSplitBy(cluster, heterogeneity) {
  const splits = []
  if (heterogeneity.routeAreas > 1) splits.push('routeArea')
  if (heterogeneity.renderContexts > 1) splits.push('renderContext')
  if (cluster.surfaceRole === 'input' && heterogeneity.inputIntents > 1) splits.push('inputIntent')
  if (cluster.surfaceRole === 'interactive-control' && heterogeneity.operationKinds > 1) splits.push('operationKind')
  if (cluster.surfaceRole === 'interactive-control' && heterogeneity.iconSizes > 1) splits.push('iconSize')
  if (cluster.surfaceRole === 'card-or-panel' && heterogeneity.featureDomains > 1) splits.push('featureDomain')
  if (heterogeneity.classHashes > Math.max(4, Math.ceil(cluster.entityCount / 3))) splits.push('classHash')
  return splits
}

function blockingReasons(cluster, antiMerge, heterogeneity, splits) {
  const reasons = [...antiMerge]
  if (cluster.entityCount >= 50 && splits.length > 0) reasons.push('large-heterogeneous-cluster')
  if (cluster.surfaceRole === 'input' && cluster.inputIntents.includes('unknown')) reasons.push('unknown-input-intent')
  if (cluster.surfaceRole === 'interactive-control' && cluster.operationKinds.includes('unknown')) reasons.push('unknown-operation-kind')
  if (heterogeneity.renderContexts > 1) reasons.push('multiple-render-contexts')
  if (heterogeneity.iconSizes > 3) reasons.push('many-icon-sizes')
  return [...new Set(reasons)].sort()
}

function confidenceScore(cluster, antiMerge, heterogeneity, splits) {
  let score = 92
  score -= antiMerge.length * 14
  score -= Math.max(0, heterogeneity.routeAreas - 1) * 10
  score -= Math.max(0, heterogeneity.renderContexts - 1) * 9
  score -= Math.max(0, heterogeneity.inputIntents - 1) * 8
  score -= Math.max(0, heterogeneity.operationKinds - 1) * 6
  score -= Math.max(0, heterogeneity.iconSizes - 1) * 4
  score -= splits.length * 5
  if (cluster.entityCount > 80) score -= 10
  if (cluster.entityCount > 150) score -= 10
  return Math.max(0, Math.min(100, score))
}

function priorityScore(cluster, confidence, blockers) {
  const impact = Math.min(45, Math.round(cluster.occurrenceCount / 4))
  const spread = Math.min(20, cluster.files)
  const confidencePart = Math.round(confidence / 4)
  const blockerPenalty = blockers.length * 8
  return Math.max(0, impact + spread + confidencePart - blockerPenalty)
}

function requiredEvidenceRoutes(cluster) {
  const routes = new Set()
  for (const area of cluster.distinctRouteAreas) {
    if (area === 'dash' || area === 'dashboard-components') routes.add('dash')
    else if (area === 'admin') routes.add('admin')
    else if (area === 'auth') routes.add('auth')
    else if (area === 'public-org') routes.add('courses')
  }
  if (cluster.renderContexts.includes('editor')) routes.add('boards')
  if (cluster.featureDomains.includes('boards')) routes.add('boards')
  if (cluster.featureDomains.includes('courses')) routes.add('courses')
  return [...routes].sort()
}

function scannedSourcesGitHead() {
  try {
    const relRoot = relative(REPO_ROOT, WEB_ROOT).split('\\').join('/')
    const globBase = relRoot ? `${relRoot}/` : ''
    return execFileSync(
      'git',
      ['log', '-1', '--format=%H', '--', `:(glob)${globBase}**/*.ts`, `:(glob)${globBase}**/*.tsx`],
      { cwd: REPO_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
    ).trim().slice(0, 12)
  } catch {
    return 'unknown'
  }
}

function scannedSourcesFingerprint(files) {
  const digest = createHash('sha256')
  for (const file of files) {
    digest.update(relPath(file))
    digest.update('\0')
    digest.update(readFileSync(file, 'utf8'))
    digest.update('\0')
  }
  return digest.digest('hex').slice(0, 16)
}

const files = walk(WEB_ROOT)
const sourceFingerprint = scannedSourcesFingerprint(files)
const parsed = new Map()
const exportedConstValues = new Map()

for (const file of files) {
  const source = readFileSync(file, 'utf8')
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKind(file))
  const consts = collectConstValues(sourceFile)
  const imports = collectImports(sourceFile, file)
  parsed.set(file, { source, sourceFile, localConsts: consts.local, exportedConsts: consts.exported, ...imports })
  for (const [name, value] of consts.exported) exportedConstValues.set(`${file}:${name}`, value)
}

const occurrences = []
const entityMap = new Map()
const gramMap = new Map()
let occurrenceIndex = 0

function addOccurrence(ctx, sourceNode, classValue, sourceExpressionKind) {
  const opening = nearestJsxOpening(sourceNode)
  const tag = getTagName(opening, ctx.sourceFile) ?? 'non-jsx'
  const location = pos(ctx.sourceFile, sourceNode)
  const tokens = tokensOf(classValue)
  const ancestors = ancestorChain(sourceNode, ctx.sourceFile)
  const interactiveRoot = opening ? findInteractiveRoot(opening, ctx) : undefined
  const rootOpening = interactiveRoot
    ? nearestInteractiveOpening(opening, ctx)
    : undefined
  const roles = rootOpening ? collectRoleElements(rootOpening, ctx) : []
  const props = opening ? propsSummary(opening, ctx) : {}
  const route = routeInfo(ctx.rel)
  const role = surfaceRole(ctx.rel, tag, tokens, ancestors, props)
  const context = renderContext(ctx.rel, ancestors, role)
  const intent = inputIntent(ctx.rel, tag, props, context)
  const classFamilies = [...new Set(tokens.map(tokenFamily))].sort()
  const variants = variantPrefixes(tokens)
  const operation = operationKind(tag, props, ctx.rel, roles, tokens)
  const risk = interactionRisk(role, context, operation, props)
  const entityId = interactiveRoot?.id ?? `${ctx.rel}:L${location.line}:${tag}:${hash(classValue)}`
  const id = `occ:${hash(`${ctx.rel}:${location.offset}:${classValue}:${occurrenceIndex++}`)}`

  const occurrence = {
    id,
    entityId,
    file: ctx.rel,
    line: location.line,
    column: location.column,
    componentOwner: nearestComponentOwner(sourceNode, ctx.sourceFile),
    jsxElement: tag,
    importSource: importedSourceFor(tag, ctx),
    sourceExpressionKind,
    classSource: sourceExpressionKind,
    fullClassName: classValue,
    fullClassNameHash: hash(classValue),
    tokens,
    tokenFamilies: classFamilies,
    variantPrefixes: variants,
    tokenCount: tokens.length,
    routeArea: route.area,
    featureDomain: featureDomain(ctx.rel),
    renderContext: context,
    surfaceRole: role,
    inputIntent: intent,
    operationKind: operation,
    interactionRisk: risk,
    interactiveRoot,
    props,
    ancestorChain: ancestors,
  }
  occurrences.push(occurrence)

  for (const gram of ngrams(tokens)) {
    let row = gramMap.get(gram)
    if (!row) {
      row = { gram, occurrenceIds: new Set(), files: new Set(), chars: gram.length, tokens: tokensOf(gram).length }
      gramMap.set(gram, row)
    }
    row.occurrenceIds.add(id)
    row.files.add(ctx.rel)
  }

  let entity = entityMap.get(entityId)
  if (!entity) {
    entity = {
      id: entityId,
      file: ctx.rel,
      line: interactiveRoot?.line ?? location.line,
      componentOwner: occurrence.componentOwner,
      routeArea: route.area,
      interactiveTag: interactiveRoot?.tag ?? tag,
      surfaceRole: role,
      props: interactiveRoot?.props ?? props,
      occurrenceIds: new Set(),
      roles: new Map(),
      iconSizes: new Set(),
      iconComponents: new Set(),
      classHashes: new Set(),
      classSamples: new Set(),
      tokenFamilies: new Set(),
      variantPrefixes: new Set(),
      sourceExpressionKinds: new Set(),
      renderContexts: new Set(),
      featureDomains: new Set(),
      inputIntents: new Set(),
      operationKinds: new Set(),
      interactionRisks: new Set(),
    }
    entityMap.set(entityId, entity)
  }
  entity.occurrenceIds.add(id)
  entity.classHashes.add(occurrence.fullClassNameHash)
  entity.classSamples.add(classValue)
  entity.sourceExpressionKinds.add(sourceExpressionKind)
  entity.renderContexts.add(context)
  entity.featureDomains.add(occurrence.featureDomain)
  entity.operationKinds.add(operation)
  entity.interactionRisks.add(risk)
  if (intent) entity.inputIntents.add(intent)
  for (const family of classFamilies) entity.tokenFamilies.add(family)
  for (const variant of variants) entity.variantPrefixes.add(variant)
  for (const siblingRole of roles) {
    entity.roles.set(`${siblingRole.role}:${siblingRole.tag}`, siblingRole)
    if (siblingRole.role === 'icon' || siblingRole.role === 'chevron') {
      if (siblingRole.size !== undefined) entity.iconSizes.add(siblingRole.size)
      entity.iconComponents.add(siblingRole.tag)
    }
  }
}

function nearestInteractiveOpening(opening, ctx) {
  let current = owningJsxElement(opening)
  while (current) {
    const currentOpening = jsxOpeningFor(current)
    const tag = getTagName(currentOpening, ctx.sourceFile)
    if (tag && (INTERACTIVE_TAGS.has(tag) || hasEventOrHref(currentOpening))) return currentOpening
    current = current.parent
  }
  return undefined
}

for (const [file, data] of parsed) {
  const rel = relPath(file)
  const ctx = { ...data, absPath: file, rel, exportedConstValues }

  function visit(node) {
    if (ts.isJsxAttribute(node) && (node.name.getText() === 'className' || node.name.getText() === 'class')) {
      if (node.initializer) {
        for (const item of extractClassValues(node.initializer, ctx, `jsx-attr:${expressionKind(node.initializer, ctx)}`)) {
          addOccurrence(ctx, item.node, item.value, item.sourceExpressionKind)
        }
      }
    }

    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const value = literalValue(node.initializer)
      if (typeof value === 'string' && isClassLike(value)) {
        addOccurrence(ctx, node.initializer, value, `const:${node.name.text}`)
      }
    }

    ts.forEachChild(node, visit)
  }
  visit(data.sourceFile)
}

const gramRows = stableEntries(gramMap)
  .map(([gram, row]) => {
    const occurrencesCount = row.occurrenceIds.size
    return {
      gram,
      occurrences: occurrencesCount,
      files: row.files.size,
      chars: row.chars,
      tokens: row.tokens,
      savings: occurrencesCount * (row.chars - OVERHEAD),
      sampleOccurrenceIds: [...row.occurrenceIds].sort().slice(0, 3),
    }
  })
  .filter((row) => row.occurrences >= MIN_OCCURRENCES && row.savings > 0)
  .sort((a, b) => b.savings - a.savings || b.occurrences - a.occurrences || a.gram.localeCompare(b.gram))

const entities = stableEntries(entityMap).map(([id, entity]) => ({
  id,
  file: entity.file,
  line: entity.line,
  componentOwner: entity.componentOwner,
  routeArea: entity.routeArea,
  interactiveTag: entity.interactiveTag,
  surfaceRole: entity.surfaceRole,
  props: entity.props,
  occurrenceCount: entity.occurrenceIds.size,
  sampleOccurrenceIds: [...entity.occurrenceIds].sort().slice(0, 8),
  tokenFamilies: [...entity.tokenFamilies].sort(),
  variantPrefixes: [...entity.variantPrefixes].sort(),
  sourceExpressionKinds: [...entity.sourceExpressionKinds].sort(),
  renderContexts: [...entity.renderContexts].sort(),
  featureDomains: [...entity.featureDomains].sort(),
  inputIntents: [...entity.inputIntents].sort(),
  operationKinds: [...entity.operationKinds].sort(),
  interactionRisks: [...entity.interactionRisks].sort(),
  roles: [...entity.roles.values()].sort((a, b) => a.role.localeCompare(b.role) || a.tag.localeCompare(b.tag)),
  iconSizes: [...entity.iconSizes].sort((a, b) => a - b),
  iconComponents: [...entity.iconComponents].sort(),
  classHashCount: entity.classHashes.size,
  sampleClassHashes: [...entity.classHashes].sort().slice(0, 8),
  classSamples: [...entity.classSamples].sort().slice(0, 6),
}))
const reportedEntities = entities.filter((entity) =>
  entity.occurrenceCount > 1 ||
  entity.roles.length > 0 ||
  entity.surfaceRole !== 'structural'
)

const clustersByFingerprint = new Map()
for (const entity of entities) {
  const roleSignature = entity.roles.map((role) => role.role).sort().join('+') || 'no-child-roles'
  const fingerprint = [
    entity.surfaceRole,
    entity.routeArea,
    entity.interactiveTag,
    roleSignature,
  ].join('|')
  let cluster = clustersByFingerprint.get(fingerprint)
  if (!cluster) {
    cluster = {
      clusterId: `cluster:${hash(fingerprint)}`,
      fingerprint,
      surfaceRole: entity.surfaceRole,
      entityIds: [],
      files: new Set(),
      routeAreas: new Set(),
      interactiveTags: new Set(),
      roleNames: new Set(),
      iconSizes: new Set(),
      iconComponents: new Set(),
      classHashes: new Set(),
      tokenFamilies: new Set(),
      variantPrefixes: new Set(),
      sourceExpressionKinds: new Set(),
      renderContexts: new Set(),
      featureDomains: new Set(),
      inputIntents: new Set(),
      operationKinds: new Set(),
      interactionRisks: new Set(),
      samples: [],
    }
    clustersByFingerprint.set(fingerprint, cluster)
  }
  cluster.entityIds.push(entity.id)
  cluster.files.add(entity.file)
  cluster.routeAreas.add(entity.routeArea)
  cluster.interactiveTags.add(entity.interactiveTag)
  for (const role of entity.roles) cluster.roleNames.add(role.role)
  for (const size of entity.iconSizes) cluster.iconSizes.add(size)
  for (const component of entity.iconComponents) cluster.iconComponents.add(component)
  for (const classHash of entity.sampleClassHashes) cluster.classHashes.add(classHash)
  for (const family of entity.tokenFamilies) cluster.tokenFamilies.add(family)
  for (const variant of entity.variantPrefixes) cluster.variantPrefixes.add(variant)
  for (const kind of entity.sourceExpressionKinds) cluster.sourceExpressionKinds.add(kind)
  for (const context of entity.renderContexts) cluster.renderContexts.add(context)
  for (const domain of entity.featureDomains) cluster.featureDomains.add(domain)
  for (const intent of entity.inputIntents) cluster.inputIntents.add(intent)
  for (const operation of entity.operationKinds) cluster.operationKinds.add(operation)
  for (const risk of entity.interactionRisks) cluster.interactionRisks.add(risk)
  if (cluster.samples.length < 5) cluster.samples.push({ file: entity.file, line: entity.line, componentOwner: entity.componentOwner })
}

const semanticClusters = stableEntries(clustersByFingerprint)
  .map(([, cluster]) => {
    const result = {
      clusterId: cluster.clusterId,
      fingerprint: cluster.fingerprint,
      surfaceRole: cluster.surfaceRole,
      entityCount: cluster.entityIds.length,
      occurrenceCount: cluster.entityIds.reduce((sum, id) => sum + (entityMap.get(id)?.occurrenceIds.size ?? 0), 0),
      files: cluster.files.size,
      distinctRouteAreas: [...cluster.routeAreas].sort(),
      uniqueInteractiveTags: [...cluster.interactiveTags].sort(),
      roles: [...cluster.roleNames].sort(),
      iconSizes: [...cluster.iconSizes].sort((a, b) => a - b),
      iconComponents: [...cluster.iconComponents].sort(),
      tokenFamilies: [...cluster.tokenFamilies].sort(),
      variantPrefixes: [...cluster.variantPrefixes].sort(),
      sourceExpressionKinds: [...cluster.sourceExpressionKinds].sort(),
      renderContexts: [...cluster.renderContexts].sort(),
      featureDomains: [...cluster.featureDomains].sort(),
      inputIntents: [...cluster.inputIntents].sort(),
      operationKinds: [...cluster.operationKinds].sort(),
      interactionRisks: [...cluster.interactionRisks].sort(),
      classHashCount: cluster.classHashes.size,
      sampleClassHashes: [...cluster.classHashes].sort().slice(0, 8),
      sampleEntityIds: cluster.entityIds.sort().slice(0, 8),
      samples: cluster.samples,
    }
    const antiMerge = antiMergeReasons(result)
    const heterogeneity = clusterHeterogeneity(result)
    const splits = recommendedSplitBy(result, heterogeneity)
    const blockers = blockingReasons(result, antiMerge, heterogeneity, splits)
    const confidence = confidenceScore(result, antiMerge, heterogeneity, splits)
    return {
      ...result,
      decision: clusterDecision(result),
      antiMergeReasons: antiMerge,
      heterogeneity,
      recommendedSplitBy: splits,
      blockingReasons: blockers,
      confidenceScore: confidence,
      priorityScore: priorityScore(result, confidence, blockers),
      requiredEvidenceRoutes: requiredEvidenceRoutes(result),
      inference: 'heuristic-ast-no-typechecker',
    }
  })
  .filter((cluster) => cluster.entityCount >= 2 || cluster.occurrenceCount >= 3)
  .sort((a, b) => b.occurrenceCount - a.occurrenceCount || b.entityCount - a.entityCount || a.fingerprint.localeCompare(b.fingerprint))

function isReportedOccurrence(occurrence) {
  const ancestry = occurrence.ancestorChain.join('/')
  return occurrence.surfaceRole !== 'structural' ||
    /Dashboard\/Menus|sidebar|Button|Input|Command|Dropdown|HoverMenu/.test(`${occurrence.file}/${ancestry}`)
}

const reportedRows = gramRows.slice(0, 2000)
const reportedOccurrences = occurrences
  .filter(isReportedOccurrence)
  .sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.column - b.column || a.id.localeCompare(b.id))

const output = {
  schemaVersion: 'classname-token-mining.v2',
  generator: '.harness/lib/classname-miner-v2.mjs',
  gitHead: scannedSourcesGitHead(),
  sourceFingerprint,
  params: { MIN_CHARS, MIN_TOKENS, MAX_TOKENS, MIN_OCCURRENCES, OVERHEAD },
  scanned: files.length,
  counts: {
    occurrences: occurrences.length,
    gramRows: gramRows.length,
    reportedRows: reportedRows.length,
    reportedOccurrences: reportedOccurrences.length,
    entities: entities.length,
    reportedEntities: reportedEntities.length,
    semanticClusters: semanticClusters.length,
  },
  rows: reportedRows,
  occurrences: reportedOccurrences,
  entities: reportedEntities,
  semanticClusters,
}

// Modo dataset COMPLETO (nao-truncado) p/ ingestao relacional. Nao sobrescreve o JSON/MD canonico.
const emitFullIdx = process.argv.indexOf('--emit-full')
if (emitFullIdx !== -1) {
  const fullDir = process.argv[emitFullIdx + 1]
  if (!fullDir) throw new Error('--emit-full exige um diretorio de saida')
  const toNdjson = (list) => `${list.map((row) => JSON.stringify(row)).join('\n')}\n`
  mkdirSync(fullDir, { recursive: true })
  writeFileSync(join(fullDir, 'run.ndjson'), `${JSON.stringify({
    schemaVersion: output.schemaVersion,
    generator: output.generator,
    gitHead: output.gitHead,
    sourceFingerprint: output.sourceFingerprint,
    scanned: output.scanned,
    params: output.params,
    counts: output.counts,
  })}\n`)
  writeFileSync(join(fullDir, 'occ.ndjson'), toNdjson(occurrences))
  writeFileSync(join(fullDir, 'ent.ndjson'), toNdjson(entities))
  writeFileSync(join(fullDir, 'ngram.ndjson'), toNdjson(gramRows))
  writeFileSync(join(fullDir, 'cluster.ndjson'), toNdjson(semanticClusters))
  console.log(`emit-full: dataset COMPLETO em ${fullDir} (occ=${occurrences.length} ent=${entities.length} ngram=${gramRows.length} cluster=${semanticClusters.length}); JSON/MD canonico NAO sobrescrito`)
  process.exit(0)
}

mkdirSync(OUT_DIR, { recursive: true })
// Para datasets grandes, prefira --emit-full (NDJSON) a --emit-json (JSON monolitico
// truncado). --emit-json existe so para arqueologia/backup manual pontual.
if (process.argv.includes('--emit-json')) {
  writeFileSync(OUT_JSON, `${JSON.stringify(output, null, 2)}\n`)
}

const topGrams = gramRows.slice(0, 25)
const topClusters = semanticClusters.slice(0, 20)
const highSignalClusters = semanticClusters
  .filter((cluster) =>
    !cluster.antiMergeReasons.includes('generic-structural-classes') &&
    (cluster.roles.length > 0 || cluster.decision !== 'review_required')
  )
  .slice(0, 20)
const sidebarClusters = semanticClusters
  .filter((cluster) => cluster.surfaceRole === 'sidebar-nav-item' && cluster.roles.length > 0)
  .slice(0, 12)
const markdown = `# Mineração AST/JSX de className v2

> Gerado por \`.harness/lib/classname-miner-v2.mjs\`. Diferente do v1, este arquivo não é cânone: é dado enriquecido para triagem de reabstração. O v2 preserva ocorrências com path/linha, componente dono, elemento JSX, ancestralidade, raiz interativa, roles de siblings e clusters semânticos.

## Resumo

- Git HEAD dos sources escaneados: \`${output.gitHead}\`
- Fingerprint dos sources escaneados: \`${output.sourceFingerprint}\`
- Arquivos varridos: ${output.scanned}
- Ocorrências de classes: ${output.counts.occurrences}
- N-grams candidatos: ${output.counts.gramRows}
- N-grams reportados no JSON: ${output.counts.reportedRows}
- Ocorrências reportadas no JSON: ${output.counts.reportedOccurrences}
- Entidades JSX/interativas: ${output.counts.entities}
- Entidades reportadas no JSON: ${output.counts.reportedEntities}
- Clusters semânticos: ${output.counts.semanticClusters}

## Top n-grams por economia

| # | gram | ocorr. | arq. | chars | economia |
|---|---|---:|---:|---:|---:|
${topGrams.map((row, index) => `| ${index + 1} | \`${row.gram}\` | ${row.occurrences} | ${row.files} | ${row.chars} | ${row.savings} |`).join('\n')}

## Top clusters semânticos

| # | cluster | surface | decisão | conf. | entidades | ocorr. | split | bloqueios |
|---|---|---|---|---:|---:|---:|---|---|
${topClusters.map((cluster, index) => `| ${index + 1} | \`${cluster.clusterId}\` | \`${cluster.surfaceRole}\` | \`${cluster.decision}\` | ${cluster.confidenceScore} | ${cluster.entityCount} | ${cluster.occurrenceCount} | \`${cluster.recommendedSplitBy.join(', ') || '-'}\` | \`${cluster.blockingReasons.join(', ') || '-'}\` |`).join('\n')}

## Clusters de alto sinal

| # | cluster | surface | decisão | prioridade | conf. | entidades | ocorr. | tags | split |
|---|---|---|---|---:|---:|---:|---:|---|---|
${highSignalClusters.map((cluster, index) => `| ${index + 1} | \`${cluster.clusterId}\` | \`${cluster.surfaceRole}\` | \`${cluster.decision}\` | ${cluster.priorityScore} | ${cluster.confidenceScore} | ${cluster.entityCount} | ${cluster.occurrenceCount} | \`${cluster.uniqueInteractiveTags.join(', ') || '-'}\` | \`${cluster.recommendedSplitBy.join(', ') || '-'}\` |`).join('\n')}

## Evidência específica da sidebar

| # | cluster | fingerprint | entidades | ocorr. | roles | icon sizes | amostra |
|---|---|---|---:|---:|---|---|---|
${sidebarClusters.map((cluster, index) => {
  const sample = cluster.samples[0]
  const sampleText = sample ? `${sample.file}:L${sample.line} ${sample.componentOwner}` : '-'
  return `| ${index + 1} | \`${cluster.clusterId}\` | \`${cluster.fingerprint}\` | ${cluster.entityCount} | ${cluster.occurrenceCount} | \`${cluster.roles.join(', ') || '-'}\` | \`${cluster.iconSizes.join(', ') || '-'}\` | \`${sampleText}\` |`
}).join('\n')}

## Como interpretar

- \`rows\`: repetição textual de class-tokens; ainda pode ser idioma Tailwind genérico.
- \`occurrences\`: evidência local com JSX, ancestralidade e raiz interativa.
- \`entities\`: agrupamento por raiz JSX/interativa.
- \`semanticClusters\`: candidatos de reabstração. A decisão final exige contrato, migração sequencial e evidência visual.
- \`blockingReasons\`, \`recommendedSplitBy\`, \`confidenceScore\` e \`priorityScore\`: inferência heurística de AST sintática, sem TypeChecker; bloqueiam migração automática quando houver heterogeneidade.

## Guardrail

Não promover cluster para token/componente apenas por economia. Use \`surfaceRole\`, \`roles\`, \`routeArea\`, \`interactiveTag\`, \`antiMergeReasons\`, \`blockingReasons\`, \`recommendedSplitBy\` e amostras antes de alterar código.
`
writeFileSync(OUT_MD, markdown)

if (process.argv.includes('--self-test')) {
  // Generico: valida a FORMA do schema de saida, nao fixtures de um projeto
  // especifico. Seguro rodar em qualquer arvore, inclusive com 0 arquivos
  // .ts/.tsx (ex.: o proprio skeleton renderizado deste harness).
  const requiredKeys = ['schemaVersion', 'generator', 'gitHead', 'sourceFingerprint', 'counts', 'rows', 'occurrences', 'entities', 'semanticClusters']
  for (const key of requiredKeys) {
    if (!(key in output)) throw new Error(`self-test failed: missing ${key}`)
  }
  if (output.semanticClusters.length > 0) {
    const requiredClusterKeys = ['blockingReasons', 'recommendedSplitBy', 'confidenceScore', 'priorityScore', 'requiredEvidenceRoutes', 'inference']
    for (const key of requiredClusterKeys) {
      if (!(key in output.semanticClusters[0])) throw new Error(`self-test failed: missing cluster ${key}`)
    }
  }
  if (output.occurrences.length > 0 && !output.occurrences.some((occurrence) => Array.isArray(occurrence.tokens) && occurrence.tokens.length > 0)) {
    throw new Error('self-test failed: occurrences do not expose tokens')
  }
  console.log(`self-test: OK (scanned=${output.scanned}, occurrences=${output.counts.occurrences}, clusters=${output.counts.semanticClusters})`)
}

console.log('=== CLASSNAME TOKEN MINER V2 ===')
console.log('Raiz varrida:', WEB_ROOT)
console.log('Arquivos:', output.scanned)
console.log('Ocorrencias:', output.counts.occurrences)
console.log('N-grams candidatos:', output.counts.gramRows)
console.log('Entidades:', output.counts.entities)
console.log('Clusters:', output.counts.semanticClusters)
console.log('Saida:', process.argv.includes('--emit-json') ? `${relPath(OUT_JSON)} + ${relPath(OUT_MD)}` : `${relPath(OUT_MD)} (JSON so com --emit-json; --emit-full <dir> p/ NDJSON completo)`)
