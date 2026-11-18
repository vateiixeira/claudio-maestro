import { afterEach, describe, expect, it, vi } from 'vitest'
import { readDigestCollapsed, writeDigestCollapsed } from '../digestCollapsePref'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Resumo recolhido no painel de detalhes', () => {
  it('começa recolhido', () => {
    expect(readDigestCollapsed()).toBe(true)
  })

  it('lembra a escolha de deixar aberto e de recolher de novo', () => {
    writeDigestCollapsed(false)
    expect(localStorage.getItem('maestro:digest-collapsed')).toBe('false')
    expect(readDigestCollapsed()).toBe(false)
    writeDigestCollapsed(true)
    expect(readDigestCollapsed()).toBe(true)
  })

  it('sem acesso ao armazenamento fica recolhido e não quebra', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloqueado') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloqueado') })
    expect(readDigestCollapsed()).toBe(true)
    expect(() => writeDigestCollapsed(false)).not.toThrow()
  })
})
