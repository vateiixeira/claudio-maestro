import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => vi.restoreAllMocks())

describe('estado recolhido do menu', () => {
  it('começa aberto, guarda e relê', async () => {
    const first = await import('../sidebarCollapse')
    expect(first.isCollapsed('project', 1)).toBe(false)
    first.setCollapsed('project', 1, true)
    first.setCollapsed('group', 7, true)
    vi.resetModules()
    const again = await import('../sidebarCollapse')
    expect(again.isCollapsed('project', 1)).toBe(true)
    expect(again.isCollapsed('group', 7)).toBe(true)
    again.setCollapsed('group', 7, false)
    expect(again.isCollapsed('group', 7)).toBe(false)
  })

  it('funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(false)
    mod.setCollapsed('project', 1, true)
    expect(mod.isCollapsed('project', 1)).toBe(true)
  })

  it('ignora conteúdo inválido', async () => {
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":"x"}')
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(false)
  })
})
