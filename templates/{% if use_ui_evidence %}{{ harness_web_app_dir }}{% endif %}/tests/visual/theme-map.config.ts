// theme-map.config.ts — matriz de temas do motor de evidência visual
// (evidence.spec.ts). CUSTOMIZE este arquivo para o design system real do
// seu projeto; o harness não sabe nada sobre suas classes/atributos de tema.
//
// Cada entrada é um nome de tema (o que `--themes <csv>` aceita) mapeado
// para COMO forçar esse tema na página ANTES da captura:
//   - documentAttrs: atributos aplicados via setAttribute no <html>
//     (ex.: { 'data-theme': 'acme-dark' })
//   - documentClasses: classes adicionadas via classList no <html>
//     (ex.: ['dark'] — convenção comum de Tailwind/next-themes)
//   - seedLocalStorage: pares chave/valor escritos via page.addInitScript
//     ANTES do primeiro paint (para apps que decidem o tema por
//     localStorage antes da hidratação — ex.: next-themes)
//
// Sem `--themes`/UI_EVIDENCE_THEMES explícito, evidence.spec.ts captura
// TODOS os temas declarados aqui (Object.keys deste objeto) — não há
// default hardcoded no motor, então adicionar um tema aqui já o inclui na
// captura padrão.
//
// DEFAULT (nenhum design system conhecido): um único tema "default", sem
// nenhuma manipulação de atributo/classe/localStorage — a página é
// capturada exatamente como renderiza fora da caixa.
export type ThemeState = {
  documentAttrs?: Record<string, string>
  documentClasses?: string[]
  seedLocalStorage?: Record<string, string>
}

export const THEME_STATES: Record<string, ThemeState> = {
  default: {},
}

// Exemplo real (design system com marca via data-theme + modo claro/escuro
// via classe .dark, convenção shadcn/ui/Tailwind — descomente e adapte):
//
// export const THEME_STATES: Record<string, ThemeState> = {
//   light: {},
//   dark: { documentClasses: ['dark'] },
//   'brand-b': { documentAttrs: { 'data-theme': 'brand-b' } },
//   'brand-b-dark': { documentAttrs: { 'data-theme': 'brand-b' }, documentClasses: ['dark'] },
// }
