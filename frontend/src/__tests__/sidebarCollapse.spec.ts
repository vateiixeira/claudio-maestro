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
    localStorage.setItem('maestro:sidebar-collapsed', '{"project":"x"}')
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(false)
  })

  it('guarda e relê seções recolhidas pelo nome', async () => {
    const first = await import('../sidebarCollapse')
    expect(first.isSectionCollapsed('open')).toBe(false)
    first.setSectionCollapsed('open', true)
    vi.resetModules()
    const again = await import('../sidebarCollapse')
    expect(again.isSectionCollapsed('open')).toBe(true)
    expect(again.isCollapsed('project', 1)).toBe(false)
    again.setSectionCollapsed('open', false)
    expect(again.isSectionCollapsed('open')).toBe(false)
  })

  it('seção recolhida funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../sidebarCollapse')
    expect(mod.isSectionCollapsed('open')).toBe(false)
    mod.setSectionCollapsed('open', true)
    expect(mod.isSectionCollapsed('open')).toBe(true)
  })

  it('ignora seções inválidas e mantém o formato antigo', async () => {
    localStorage.setItem('maestro:sidebar-collapsed', '{"project":[1],"section":[3,"open",null]}')
    const mod = await import('../sidebarCollapse')
    expect(mod.isCollapsed('project', 1)).toBe(true)
    expect(mod.isSectionCollapsed('open')).toBe(true)
    localStorage.setItem('maestro:sidebar-collapsed', '{"project":[2]}')
    vi.resetModules()
    const old = await import('../sidebarCollapse')
    expect(old.isCollapsed('project', 2)).toBe(true)
    expect(old.isSectionCollapsed('open')).toBe(false)
  })

  it('seção que começa recolhida lembra quando foi aberta', async () => {
    const mod = await import('../sidebarCollapse')
    expect(mod.isSectionOpened('later')).toBe(false)
    mod.setSectionOpened('later', true)
    expect(mod.isSectionOpened('later')).toBe(true)
    mod.setSectionOpened('later', false)
    expect(mod.isSectionOpened('later')).toBe(false)
  })
})
