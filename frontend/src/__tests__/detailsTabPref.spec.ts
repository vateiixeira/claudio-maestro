import { afterEach, describe, expect, it, vi } from 'vitest'
import { readDetailsTab, writeDetailsTab } from '../detailsTabPref'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('aba do painel de detalhes', () => {
  it('começa em Detalhes', () => {
    expect(readDetailsTab()).toBe('details')
  })

  it('lembra a aba Terminal', () => {
    writeDetailsTab('terminal')
    expect(localStorage.getItem('maestro:details-tab')).toBe('terminal')
    expect(readDetailsTab()).toBe('terminal')
    writeDetailsTab('details')
    expect(readDetailsTab()).toBe('details')
  })

  it('ignora um valor desconhecido', () => {
    localStorage.setItem('maestro:details-tab', 'outra')
    expect(readDetailsTab()).toBe('details')
  })

  it('segue sem armazenamento', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    expect(readDetailsTab()).toBe('details')
    expect(() => writeDetailsTab('terminal')).not.toThrow()
  })
})
