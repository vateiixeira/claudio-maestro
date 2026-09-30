import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { removeLegacyStorage } from '../legacyStorage'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('limpeza de chaves antigas do localStorage', () => {
  it('remove a chave dos Recentes antigos e não toca em mais nada', () => {
    localStorage.setItem('vibing:recent-conversations', JSON.stringify(['a', 'b']))
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":[1],"group":[]}')
    localStorage.setItem('vibing:details-open', 'true')
    localStorage.setItem('outro-app:recent-conversations', 'x')

    removeLegacyStorage()

    expect(localStorage.getItem('vibing:recent-conversations')).toBeNull()
    expect(localStorage.length).toBe(3)
    expect(localStorage.getItem('vibing:sidebar-collapsed')).toBe('{"project":[1],"group":[]}')
    expect(localStorage.getItem('vibing:details-open')).toBe('true')
    expect(localStorage.getItem('outro-app:recent-conversations')).toBe('x')
  })

  it('não falha sem a chave nem com o localStorage quebrado', () => {
    expect(() => removeLegacyStorage()).not.toThrow()
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('x') })
    expect(() => removeLegacyStorage()).not.toThrow()
  })
})
