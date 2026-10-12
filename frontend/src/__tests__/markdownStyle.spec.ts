/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Read from disk: Vitest turns a CSS import into an empty module.
const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../style.css'), 'utf8') // independent of the cwd
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

  it('listas do markdown têm marcadores, com marcador discreto', () => {
    expect(rule('.markdown ul')).toMatch(/list-style:\s*disc/)
    expect(rule('.markdown ol')).toMatch(/list-style:\s*decimal/)
    expect(rule('.markdown ul ul')).toMatch(/list-style:\s*circle/)
    expect(rule('.markdown li::marker')).toMatch(/color:\s*var\(--color-fg-subtle\)/)
    // Scoped to .markdown: no bare `ul`/`ol` rule that would bring bullets back to lists elsewhere.
    expect(css).not.toMatch(/(?:^|\n)(?:ul|ol)\s*[,{]/)
  })

  describe('realce de sintaxe', () => {
    const hljs = (cls: string) => rule(cls)
    const color = (decl: string) => decl.match(/color:\s*([^;]+);/)?.[1].trim()
    const token = (name: string) => css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1]
    // Contrast ratio (WCAG) of a #rrggbb color on the page background.
    const luminance = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
    const contrast = (a: string, b: string) => {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
      return (hi + 0.05) / (lo + 0.05)
    }

    it('cada classe usa o token de sintaxe do tema, nunca as cores de sinal (laranja, verde, vermelho, azul)', () => {
      const expected: Record<string, string> = {
        '.hljs-keyword, .hljs-selector-tag, .hljs-built_in, .hljs-meta': 'syntax-keyword',
        '.hljs-string, .hljs-attr, .hljs-regexp': 'syntax-string',
        '.hljs-comment, .hljs-quote': 'syntax-comment',
        '.hljs-number, .hljs-literal': 'syntax-number',
        '.hljs-title': 'syntax-function',
        '.hljs-type': 'syntax-type',
      }
      for (const [selector, name] of Object.entries(expected)) {
        const decl = hljs(selector)
        expect(color(decl), selector).toBe(`var(--color-${name})`)
        expect(decl, selector).not.toMatch(/--color-(primary|secondary|info|diff)/)
      }
    })

    it('no tema Maestro o realce continua sóbrio: neutros e o lilás das strings', () => {
      for (const name of ['keyword', 'function', 'type']) expect(token(`syntax-${name}`), name).toBe(token('fg'))
      expect(token('syntax-number')).toBe(token('code-fg'))
      expect(token('syntax-comment')).toBe(token('fg-subtle'))
      expect(token('syntax-string')).toBe('#c9b8e0')
    })

    it('strings do Maestro têm contraste AA sobre o fundo', () => {
      expect(contrast(token('syntax-string')!, '#0b0b0c')).toBeGreaterThanOrEqual(4.5)
    })

    it('keywords e títulos usam o peso da variável (600 no Maestro); comentários em itálico', () => {
      expect(css.match(/:root\s*\{([^}]*)\}/)?.[1]).toMatch(/--syntax-weight:\s*600/)
      for (const selector of ['.hljs-keyword, .hljs-selector-tag, .hljs-built_in, .hljs-meta', '.hljs-title', '.hljs-type']) {
        expect(hljs(selector), selector).toMatch(/font-weight:\s*var\(--syntax-weight\)/)
      }
      expect(hljs('.hljs-comment, .hljs-quote')).toMatch(/font-style:\s*italic/)
    })

    it('linhas de diff mantêm verde e vermelho', () => {
      expect(hljs('.hljs-addition')).toMatch(/--color-diff-add-fg/)
      expect(hljs('.hljs-deletion')).toMatch(/--color-diff-del-fg/)
    })
  })
})
