import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// Characters that used to stand in for icons. Icons are inline SVG (components/icons); a glyph here renders with the
// font's metrics, so it blurs, misaligns and cannot follow `currentColor` strokes. Text separators ("·", "−") are fine.
const GLYPHS = /[▸▾⋯⤢×▤＋›‹✓✕]/

// Files owned by other tasks of milestone 17, still being converted. Remove each entry when its file is done.
const PENDING = new Set(['views/ConversationView.vue', 'components/conversation/ConversationHeader.vue'])

const root = join(__dirname, '..')
function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : vueFiles(path)
    return name.endsWith('.vue') ? [path] : []
  })
}

describe('ícones', () => {
  it('nenhum componente usa caractere de texto como ícone', () => {
    const offenders = vueFiles(root)
      .map((path) => relative(root, path))
      .filter((path) => !PENDING.has(path))
      .flatMap((path) =>
        readFileSync(join(root, path), 'utf8')
          .split('\n')
          // Code comments may mention a glyph; only the rendered template and script strings matter.
          .filter((line) => !/^\s*(\/\/|\*|<!--)/.test(line))
          .filter((line) => GLYPHS.test(line))
          .map((line) => `${path}: ${line.trim()}`),
      )
    expect(offenders).toEqual([])
  })
})
