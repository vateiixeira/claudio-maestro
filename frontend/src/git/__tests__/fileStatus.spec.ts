import { describe, expect, it } from 'vitest'
import { fileStatusText } from '../fileStatus'

describe('fileStatusText', () => {
  it('traduz o tipo de cada arquivo', () => {
    expect(fileStatusText({ path: 'a', status: 'unstaged', kind: 'M', added: 1, removed: 1 })).toBe('modificado')
    expect(fileStatusText({ path: 'a', status: 'staged', kind: 'A', added: 1, removed: 0 })).toBe('novo')
    expect(fileStatusText({ path: 'a', status: 'untracked', added: null, removed: null })).toBe('novo')
    expect(fileStatusText({ path: 'a', status: 'unstaged', kind: 'D', added: 0, removed: 3 })).toBe('apagado')
    expect(fileStatusText({ path: 'a', status: 'staged', kind: 'R', added: 0, removed: 0 })).toBe('renomeado')
    expect(fileStatusText({ path: 'a', status: 'conflict', kind: 'U', added: null, removed: null })).toBe('em conflito')
  })

  it('sem kind (backend antigo): modificado', () => {
    expect(fileStatusText({ path: 'a', status: 'unstaged', added: 1, removed: 0 })).toBe('modificado')
  })
})
