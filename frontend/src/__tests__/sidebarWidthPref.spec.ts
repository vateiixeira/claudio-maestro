import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => vi.restoreAllMocks())

describe('largura do menu lateral', () => {
  it('começa em 288 e relê o que foi salvo, dentro dos limites', async () => {
    const mod = await import('../sidebarWidthPref')
    expect(mod.readSidebarWidth()).toBe(288)
    mod.writeSidebarWidth(350.4)
    expect(localStorage.getItem('maestro:sidebar-width')).toBe('350')
    expect(mod.readSidebarWidth()).toBe(350)
    localStorage.setItem('maestro:sidebar-width', '9999')
    expect(mod.readSidebarWidth()).toBe(480)
    localStorage.setItem('maestro:sidebar-width', '10')
    expect(mod.readSidebarWidth()).toBe(240)
    localStorage.setItem('maestro:sidebar-width', 'abc')
    expect(mod.readSidebarWidth()).toBe(288)
  })

  it('o ref compartilhado começa com o valor salvo', async () => {
    localStorage.setItem('maestro:sidebar-width', '320')
    const mod = await import('../sidebarWidthPref')
    expect(mod.sidebarWidth.value).toBe(320)
  })

  it('funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../sidebarWidthPref')
    expect(mod.readSidebarWidth()).toBe(288)
    expect(() => mod.writeSidebarWidth(300)).not.toThrow()
  })

  it('clampSidebarWidth arredonda e limita', async () => {
    const { clampSidebarWidth } = await import('../sidebarWidthPref')
    expect(clampSidebarWidth(100)).toBe(240)
    expect(clampSidebarWidth(1000)).toBe(480)
    expect(clampSidebarWidth(300.6)).toBe(301)
  })
})
