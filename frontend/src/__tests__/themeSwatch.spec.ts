/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { THEMES } from '../theme'

// Read from disk: Vitest turns a CSS import into an empty module.
const read = (file: string) => readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '..', file), 'utf8')
const style = read('style.css')
const themesCss = read('themes.css')

const value = (block: string, name: string) => block.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1].toLowerCase()
const blockOf = (id: string) =>
  id === 'maestro'
    ? (style.match(/@theme\s*\{([^}]*)\}/)?.[1] ?? '')
    : (themesCss.match(new RegExp(`:root\\[data-theme='${id}'\\]\\s*\\{([^}]*)\\}`))?.[1] ?? '')

describe('amostras de cor dos cartões de tema', () => {
  it.each(THEMES.map((t) => t.id))('%s: a amostra é [bg, fg, primary, secondary] do CSS', (id) => {
    const theme = THEMES.find((t) => t.id === id)!
    const block = blockOf(id)
    expect(block, `bloco de ${id}`).not.toBe('')
    expect([...theme.swatch]).toEqual(['bg', 'fg', 'primary', 'secondary'].map((name) => value(block, name)))
  })
})
