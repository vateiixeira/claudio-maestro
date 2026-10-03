/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest turns a CSS import into an empty module.
const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../style.css'), 'utf8')
const root = css.match(/:root\s*\{([^}]*)\}/)?.[1] ?? ''
const block = (selector: string) => css.match(new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\n\\}`))?.[1] ?? ''

describe('movimento', () => {
  it('define as duas durações e a curva em :root', () => {
    expect(root).toMatch(/--motion-state:\s*160ms\s*;/)
    expect(root).toMatch(/--motion-enter:\s*200ms\s*;/)
    expect(root).toMatch(/--ease-maestro:\s*cubic-bezier\(\s*\.2,\s*\.8,\s*\.2,\s*1\s*\)\s*;/)
  })

  it('entrada sobe 6px e aparece', () => {
    const enter = block('@keyframes maestro-enter')
    expect(enter).toMatch(/opacity:\s*0/)
    expect(enter).toMatch(/translateY\(6px\)/)
  })

  it('pop cresce de 60%', () => {
    const pop = block('@keyframes maestro-pop')
    expect(pop).toMatch(/opacity:\s*0/)
    expect(pop).toMatch(/scale\(\.6\)/)
  })

  it('o brilho usa o laranja a 28% e volta ao normal', () => {
    const glow = block('@keyframes maestro-glow')
    expect(glow).toMatch(/0 0 0 4px color-mix\(in oklab, var\(--color-secondary\) 28%, transparent\)/)
    expect(glow).toMatch(/0 0 0 0/)
  })

  it('utilitários de entrada, pop e pedido de decisão usam as variáveis', () => {
    expect(block('\\.animate-enter')).toMatch(/maestro-enter var\(--motion-enter\) var\(--ease-maestro\) both/)
    expect(block('\\.animate-pop')).toMatch(/maestro-pop var\(--motion-enter\) var\(--ease-maestro\) both/)
    expect(block('\\.animate-decision')).toMatch(/maestro-glow 700ms var\(--ease-maestro\) var\(--motion-enter\) 1/)
  })

  it('movimento reduzido continua desligando animações e transições', () => {
    const reduced = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(reduced).toMatch(/animation-duration:\s*0\.01ms !important/)
    expect(reduced).toMatch(/transition-duration:\s*0\.01ms !important/)
  })
})
