import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { migrateLegacyStorage } from '../legacyStorage'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('migração das chaves antigas do localStorage', () => {
  it('remove a chave dos Recentes antigos sem criar a versão nova', () => {
    localStorage.setItem('vibing:recent-conversations', JSON.stringify(['a', 'b']))

    migrateLegacyStorage()

    expect(localStorage.getItem('vibing:recent-conversations')).toBeNull()
    expect(localStorage.getItem('maestro:recent-conversations')).toBeNull()
  })

  it('renomeia vibing:* para maestro:* e não toca em chaves de outros apps', () => {
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":[1],"group":[]}')
    localStorage.setItem('vibing:details-width', '420')
    localStorage.setItem('vibing:new-conversation-last-project', '7')
    localStorage.setItem('outro-app:details-width', 'x')

    migrateLegacyStorage()

    expect(localStorage.getItem('maestro:sidebar-collapsed')).toBe('{"project":[1],"group":[]}')
    expect(localStorage.getItem('maestro:details-width')).toBe('420')
    expect(localStorage.getItem('maestro:new-conversation-last-project')).toBe('7')
    expect(localStorage.getItem('vibing:sidebar-collapsed')).toBeNull()
    expect(localStorage.getItem('vibing:details-width')).toBeNull()
    expect(localStorage.getItem('vibing:new-conversation-last-project')).toBeNull()
    expect(localStorage.getItem('outro-app:details-width')).toBe('x')
    expect(localStorage.length).toBe(4)
  })

  it('mantém a chave nova quando as duas existem e apaga a antiga', () => {
    localStorage.setItem('vibing:details-open', 'false')
    localStorage.setItem('maestro:details-open', 'true')

    migrateLegacyStorage()

    expect(localStorage.getItem('maestro:details-open')).toBe('true')
    expect(localStorage.getItem('vibing:details-open')).toBeNull()
  })

  it('pode rodar de novo sem mudar nada', () => {
    localStorage.setItem('vibing:project-split', '0.5')
    migrateLegacyStorage()
    migrateLegacyStorage()
    expect(localStorage.getItem('maestro:project-split')).toBe('0.5')
    expect(localStorage.length).toBe(1)
  })

  it('não falha sem chaves nem com o localStorage quebrado', () => {
    expect(() => migrateLegacyStorage()).not.toThrow()
    localStorage.setItem('vibing:details-open', 'true')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('cheio') })
    expect(() => migrateLegacyStorage()).not.toThrow()
    vi.spyOn(Storage.prototype, 'key').mockImplementation(() => { throw new Error('x') })
    expect(() => migrateLegacyStorage()).not.toThrow()
  })
})
