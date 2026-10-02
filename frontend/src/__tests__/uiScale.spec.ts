import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })
afterEach(() => {
  vi.restoreAllMocks()
  document.documentElement.style.fontSize = ''
})

describe('tamanho do texto da interface', () => {
  it('começa em 100 quando nada foi salvo', async () => {
    const mod = await import('../uiScale')
    expect(mod.UI_SCALE_DEFAULT).toBe(100)
    expect(mod.readUiScale()).toBe(100)
    expect(mod.uiScale.value).toBe(100)
  })

  it('relê um valor salvo que seja uma das opções', async () => {
    localStorage.setItem('maestro:ui-scale', '112.5')
    const mod = await import('../uiScale')
    expect(mod.readUiScale()).toBe(112.5)
    expect(mod.uiScale.value).toBe(112.5)
  })

  it('ignora valores salvos inválidos', async () => {
    const mod = await import('../uiScale')
    localStorage.setItem('maestro:ui-scale', 'abc')
    expect(mod.readUiScale()).toBe(100)
    localStorage.setItem('maestro:ui-scale', '113')
    expect(mod.readUiScale()).toBe(100)
  })

  it('setUiScale atualiza o ref, aplica no html e salva', async () => {
    const mod = await import('../uiScale')
    mod.setUiScale(125)
    expect(mod.uiScale.value).toBe(125)
    expect(document.documentElement.style.fontSize).toBe('125%')
    expect(localStorage.getItem('maestro:ui-scale')).toBe('125')
  })

  it('applyUiScale só aplica no html, sem salvar', async () => {
    const mod = await import('../uiScale')
    mod.applyUiScale(137.5)
    expect(document.documentElement.style.fontSize).toBe('137.5%')
    expect(localStorage.getItem('maestro:ui-scale')).toBeNull()
  })

  it('setUiScale ignora valores fora das opções', async () => {
    const mod = await import('../uiScale')
    mod.setUiScale(999)
    expect(mod.uiScale.value).toBe(100)
    expect(document.documentElement.style.fontSize).toBe('')
    expect(localStorage.getItem('maestro:ui-scale')).toBeNull()
  })

  it('funciona com o localStorage quebrado', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('x') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('x') })
    const mod = await import('../uiScale')
    expect(mod.readUiScale()).toBe(100)
    expect(() => mod.setUiScale(150)).not.toThrow()
    expect(mod.uiScale.value).toBe(150)
    expect(document.documentElement.style.fontSize).toBe('150%')
  })
})
