/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest turns a CSS import into an empty module.
const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../style.css'), 'utf8') // independent of the cwd
const theme = css.match(/@theme\s*\{([^}]*)\}/)?.[1] ?? ''
const token = (name: string) => theme.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`))?.[1]

const channels = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
const luminance = (rgb: number[]) => {
  const [r, g, b] = rgb.map((v) => v / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a: number[], b: number[]) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
// `amount` of the type tone over a surface (sRGB approximation of color-mix).
const tint = (fg: string, surface: string, amount: number) =>
  channels(fg).map((c, i) => c * amount + channels(surface)[i] * (1 - amount))

const TYPES = {
  'type-command': '#95c3eb',
  'type-file': '#8bd6c1',
  'type-agent': '#cbafed',
  'type-think': '#dfc48b',
}

describe('cores de tipo das ações da conversa', () => {
  it('as quatro variáveis existem no @theme com o valor do design', () => {
    for (const [name, value] of Object.entries(TYPES)) {
      expect(token(name), name).toBe(value)
    }
  })

  it('passam de 7:1 sobre o próprio fundo tingido (9%, e 14% no hover) no fundo e na superfície', () => {
    for (const name of Object.keys(TYPES)) {
      const fg = token(name)!
      for (const surface of [token('bg')!, token('surface')!]) {
        for (const amount of [0.09, 0.14]) {
          expect(contrast(channels(fg), tint(fg, surface, amount)), `${name} ${surface} ${amount}`).toBeGreaterThanOrEqual(7)
        }
      }
    }
  })

  it('sobre card, o fundo de 9% passa de 7:1 e o hover de 14% fica acima de AA reforçado (6:1)', () => {
    for (const name of Object.keys(TYPES)) {
      const fg = token(name)!
      const card = token('card')!
      expect(contrast(channels(fg), tint(fg, card, 0.09)), `${name} 9%`).toBeGreaterThanOrEqual(7)
      expect(contrast(channels(fg), tint(fg, card, 0.14)), `${name} 14%`).toBeGreaterThanOrEqual(6)
    }
  })

  it('o tom de tipo é distinto dos tons de estado (primary, secondary, info, diff)', () => {
    const state = ['primary', 'secondary', 'info', 'diff-add-fg', 'diff-del-fg'].map((n) => token(n))
    for (const name of Object.keys(TYPES)) {
      expect(state).not.toContain(token(name))
    }
  })
})
