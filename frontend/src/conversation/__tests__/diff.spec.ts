import { describe, expect, it } from 'vitest'
import { diffCounts, diffFromPatch, diffFromStrings, diffWithoutHunks, toolDiff } from '../diff'

describe('diff', () => {
  it('monta linhas a partir do structuredPatch com números', () => {
    const lines = diffFromPatch([{ oldStart: 41, oldLines: 2, newStart: 41, newLines: 2, lines: [' a', '-b', '+c'] }])
    expect(lines).toEqual([
      { kind: 'context', oldNo: 41, newNo: 41, text: 'a' },
      { kind: 'del', oldNo: 42, newNo: null, text: 'b' },
      { kind: 'add', oldNo: null, newNo: 42, text: 'c' },
    ])
  })

  it('monta a partir de old_string/new_string mantendo o que é comum', () => {
    const lines = diffFromStrings('a\nb\nc', 'a\nX\nc')
    expect(lines.map((l) => l.kind)).toEqual(['context', 'del', 'add', 'context'])
    expect(diffCounts(lines)).toEqual({ added: 1, removed: 1 })
  })

  it('Write vira só adições e MultiEdit junta as edições', () => {
    expect(diffCounts(toolDiff('Write', { content: 'a\nb' }, null))).toEqual({ added: 2, removed: 0 })
    const multi = toolDiff('MultiEdit', { edits: [{ old_string: 'a', new_string: 'b' }, { old_string: 'c', new_string: '' }] }, null)
    expect(diffCounts(multi)).toEqual({ added: 1, removed: 2 })
  })

  it('prefere structuredPatch dos detalhes do resultado', () => {
    const lines = toolDiff('Edit', { old_string: 'x', new_string: 'y' }, {
      structuredPatch: [{ oldStart: 10, oldLines: 1, newStart: 10, newLines: 1, lines: ['-p', '+q'] }],
    })
    expect(lines[0]).toMatchObject({ oldNo: 10, text: 'p' })
  })
})

describe('diff sem trechos', () => {
  it('reconhece arquivo binário e mudança de permissão', () => {
    const bin = 'diff --git a/x.png b/x.png\nindex 1..2 100644\nBinary files a/x.png and b/x.png differ\n'
    expect(diffWithoutHunks(bin)).toBe('Arquivo binário alterado')
    const mode = 'diff --git a/s.sh b/s.sh\nold mode 100644\nnew mode 100755\n'
    expect(diffWithoutHunks(mode)).toBe('Permissões alteradas')
  })
  it('vazio ou com trechos dá null', () => {
    expect(diffWithoutHunks('')).toBeNull()
    expect(diffWithoutHunks('@@ -1 +1 @@\n-a\n+b\n')).toBeNull()
  })
  it('outro texto sem trechos vira "Arquivo alterado"', () => {
    expect(diffWithoutHunks('diff --git a/a b/b\nsimilarity index 100%\nrename from a\nrename to b\n')).toBe('Arquivo alterado')
  })
})
