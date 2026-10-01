/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest turns a CSS import into an empty module.
const css = readFileSync('src/style.css', 'utf8') // vitest runs from frontend/
const rule = (selector: string) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))
  return match?.[1] ?? ''
}

describe('estilo do markdown', () => {
  it('as células da tabela quebram entre palavras, não no meio delas', () => {
    const cells = rule('.markdown th, .markdown td')
    expect(cells).toMatch(/overflow-wrap:\s*normal/)
    expect(cells).toMatch(/word-break:\s*normal/)
    // A floor on the width, so short ids ("P1-7") are not split at the hyphen.
    expect(cells).toMatch(/min-width:\s*\d+ch/)
  })

  it('a tabela rola na horizontal quando não cabe', () => {
    const table = rule('.markdown table')
    expect(table).toMatch(/overflow-x:\s*auto/)
    expect(table).toMatch(/max-width:\s*100%/)
  })

  it('código em linha não tem borda, mas mantém fundo e raio', () => {
    const code = rule('.markdown code')
    expect(code).not.toMatch(/border\s*:/)
    expect(code).toMatch(/background:\s*var\(--color-elevated\)/)
    expect(code).toMatch(/border-radius:/)
  })
})
