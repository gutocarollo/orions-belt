#!/usr/bin/env node
// gen-visual-routes.mjs — ESQUELETO. Materializa rotas concretas
// (estáticas + dinâmicas resolvidas com IDs/slugs reais de dados
// existentes) -> tests/visual/routes.json, consumido por
// evidence.spec.ts/baseline.spec.ts.
//
// PORTADO de apps/web/scripts/gen-visual-routes.mjs (harness-doador de
// referência) — plano de resgate §R3 item 5. Portado só o ESQUELETO
// (helpers add/skip, escrita dos 2 arquivos JSON, e o padrão "sem corte
// silencioso": todo pattern sem dado resolvível vai para
// routes.skipped.json em vez de simplesmente sumir). NÃO portadas: as
// chamadas de API de cursos/collections do app doador — são 100%
// específicas do domínio dele.
//
// TODO(projeto-alvo): este esqueleto não sabe nada do seu domínio.
//   1. Preencha as rotas ESTÁTICAS abaixo com `add(name, path)`.
//   2. Se houver rotas DINÂMICAS (ex.: /item/[id]), busque um ID/slug real
//      via API ou seed do seu DB e chame `add()`; sem dado disponível,
//      chame `skip(pattern, motivo)` — nunca corte a rota em silêncio.
//   3. `tests/visual/routes.json.example` mostra o formato esperado. Rode
//      este script (`node scripts/gen-visual-routes.mjs`) ou edite
//      tests/visual/routes.json à mão para produzir o arquivo real.
import { writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '../tests/visual')

const routes = []
const skipped = []
const add = (name, p) => routes.push({ name, path: p })
const skip = (pattern, reason) => skipped.push({ pattern, reason })

// --- TODO: rotas estáticas do seu projeto ---
add('home', '/')
// ;['/login', '/about'].forEach((p) =>
//   add('static_' + p.replace(/^\/+/, '').replace(/\W+/g, '_'), p),
// )

// --- TODO: rotas dinâmicas — resolva um ID/slug real antes de add(), ou skip() ---
// skip('/item/[id]', 'TODO: resolver um ID real via API/seed deste projeto')

mkdirSync(outDir, { recursive: true })
writeFileSync(path.join(outDir, 'routes.json'), JSON.stringify(routes, null, 2))
writeFileSync(path.join(outDir, 'routes.skipped.json'), JSON.stringify(skipped, null, 2))
console.log(`routes.json: ${routes.length} rota(s) | skipped: ${skipped.length} (ver routes.skipped.json)`)
