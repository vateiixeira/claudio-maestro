/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(here, '..')
// Read from disk: Vitest turns a CSS import into an empty module.
const read = (file: string) => readFileSync(resolve(srcDir, file), 'utf8')
const style = read('style.css')
const themesCss = read('themes.css')

const NEW_IDS = [
  'dracula',
  'monokai-pro',
  'monokai-machine',
  'monokai-octagon',
  'monokai-ristretto',
  'monokai-spectrum',
  'monokai-classic',
]
const IDS = ['maestro', ...NEW_IDS]
// Derived with color-mix from other tokens, so a theme does not redefine them.
const DERIVED = ['primary-tint', 'secondary-tint']

const declarations = (block: string) =>
  new Map([...block.matchAll(/--color-([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()] as const))

const maestro = declarations(style.match(/@theme\s*\{([^}]*)\}/)?.[1] ?? '')
const themes = new Map(
  [...themesCss.matchAll(/\[data-theme='([\w-]+)'\]\s*\{([^}]*)\}/g)].map((m) => [m[1], declarations(m[2])] as const),
)

const channels = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
const luminance = (rgb: number[]) => {
  const [r, g, b] = rgb.map((v) => v / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a: number[], b: number[]) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
// `amount` of `fg` over `surface` (sRGB approximation of color-mix).
const tint = (fg: string, surface: string, amount: number) =>
  channels(fg).map((c, i) => c * amount + channels(surface)[i] * (1 - amount))

describe('temas escuros: estrutura', () => {
  it('há um bloco para cada tema, o Maestro primeiro, e só esses', () => {
    expect([...themes.keys()]).toEqual(IDS)
  })

  it('o tema padrão tem os seis tokens de realce de código', () => {
    for (const name of ['keyword', 'string', 'function', 'number', 'type', 'comment']) {
      expect(maestro.has(`syntax-${name}`), `syntax-${name}`).toBe(true)
    }
  })

  it.each(IDS)('%s define todos os papéis de cor do tema padrão, e nenhum a mais', (id) => {
    const expected = [...maestro.keys()].filter((name) => !DERIVED.includes(name)).sort()
    expect([...themes.get(id)!.keys()].sort()).toEqual(expected)
  })

  it.each(IDS)('%s usa só cores #rrggbb', (id) => {
    for (const [name, value] of themes.get(id)!) expect(value, name).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('os temas novos tiram o negrito do realce de código e o Maestro mantém', () => {
    expect(themesCss.match(/--syntax-weight:\s*400;/g)).toHaveLength(NEW_IDS.length)
    expect(themesCss).toMatch(/\[data-theme='maestro'\][^}]*--syntax-weight:\s*600;/)
  })

  it('o bloco do Maestro tem os mesmos valores do @theme', () => {
    const block = themes.get('maestro')!
    for (const [name, value] of block) expect(value, name).toBe(maestro.get(name))
  })

  it('os tints são recalculados dentro de qualquer elemento com data-theme', () => {
    const rule = themesCss.match(/\[data-theme\]\s*\{([^}]*)\}/)?.[1] ?? ''
    expect(rule).toMatch(/--color-primary-tint:\s*color-mix\(/)
    expect(rule).toMatch(/--color-secondary-tint:\s*color-mix\(/)
  })
})

describe.each(NEW_IDS)('contraste de %s', (id) => {
  const t = themes.get(id)!
  const c = (name: string) => t.get(name)!
  const SURFACES = ['bg', 'surface', 'panel', 'card']
  const atLeast = (fg: string, bg: string, ratio: number) =>
    expect(contrast(channels(c(fg)), channels(c(bg))), `${fg} sobre ${bg}`).toBeGreaterThanOrEqual(ratio)

  it('o texto principal passa de 7:1 em toda superfície', () => {
    for (const s of [...SURFACES, 'elevated']) atLeast('fg', s, 7)
  })

  it('texto secundário, sinais e links passam de 4,5:1 nas superfícies', () => {
    for (const s of SURFACES) {
      for (const fg of ['fg-muted', 'fg-subtle', 'primary', 'secondary', 'info-soft']) atLeast(fg, s, 4.5)
    }
    atLeast('fg-muted', 'elevated', 4.5)
  })

  it('código em linha, botões e diffs passam de 4,5:1', () => {
    atLeast('code-fg', 'elevated', 4.5)
    atLeast('code-fg', 'bg', 4.5)
    atLeast('primary-fg', 'primary', 4.5)
    atLeast('secondary-fg', 'secondary', 4.5)
    atLeast('diff-add-fg', 'diff-add-bg', 4.5)
    atLeast('diff-del-fg', 'diff-del-bg', 4.5)
  })

  it('o realce de código passa de 4,5:1 sobre o fundo do bloco (bg)', () => {
    for (const name of ['keyword', 'string', 'function', 'number', 'type', 'comment']) atLeast(`syntax-${name}`, 'bg', 4.5)
  })

  it('os tons de tipo passam de 4,5:1 sobre o próprio fundo tingido (14%, o hover)', () => {
    for (const name of ['type-command', 'type-file', 'type-agent', 'type-think']) {
      for (const s of ['bg', 'surface', 'card']) {
        expect(contrast(channels(c(name)), tint(c(name), c(s), 0.14)), `${name} sobre ${s}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })
})

describe('nenhuma cor fixa escapa do tema', () => {
  it('style.css só tem cor literal dentro do @theme', () => {
    const rest = style.replace(/@theme\s*\{[^}]*\}/, '').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(rest.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g) ?? []).toEqual([])
  })

  it('nenhum componente ou módulo usa hex ou rgb() literal', () => {
    // NewProjectView.vue: cores de projeto escolhidas pelo usuário. theme.ts: amostras dos cartões de tema.
    // labelColor.ts: cores de etiqueta escolhidas pelo usuário (texto preto/branco e cinza de reserva).
    const allowed = ['NewProjectView.vue', 'theme.ts', 'labelColor.ts']
    const files = (readdirSync(srcDir, { recursive: true }) as string[]).filter(
      (f) =>
        /\.(vue|ts)$/.test(f) &&
        !/(^|\/)(__tests__|test)\//.test(f) &&
        !/\.spec\.ts$/.test(f) &&
        !allowed.some((name) => f.endsWith(name)),
    )
    const offenders = files.filter((f) => /#[0-9a-fA-F]{6}\b|rgba?\(/.test(read(f)))
    expect(offenders).toEqual([])
  })
})
