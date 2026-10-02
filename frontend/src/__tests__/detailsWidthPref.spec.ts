import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clampDetailsWidth, detailsMaxWidth, readDetailsWidth, writeDetailsWidth } from '../detailsWidthPref'

beforeEach(() => { localStorage.clear(); vi.resetModules() })

describe('largura do Detalhes', () => {
  it('padrão 360 e valor salvo', () => {
    expect(readDetailsWidth()).toBe(360)
    writeDetailsWidth(512)
    expect(readDetailsWidth()).toBe(512)
  })
  it('valor inválido volta ao padrão', () => {
    localStorage.setItem('maestro:details-width', 'abc')
    expect(readDetailsWidth()).toBe(360)
  })
  it('máximo é o menor entre 70% e janela menos 400 menos a barra lateral', () => {
    expect(detailsMaxWidth(2000)).toBe(1312)
    expect(detailsMaxWidth(1200)).toBe(512)
    expect(detailsMaxWidth(600)).toBe(300) // never below the minimum
  })
  it('na gaveta o máximo é 70% da janela, sem descontar conversa nem barra lateral', () => {
    expect(detailsMaxWidth(900)).toBe(300)
    expect(detailsMaxWidth(900, true)).toBe(630)
    expect(detailsMaxWidth(300, true)).toBe(300) // never below the minimum
    expect(clampDetailsWidth(5000, 900, true)).toBe(630)
  })
  it('o máximo acompanha a largura atual do menu lateral', async () => {
    const { sidebarWidth } = await import('../sidebarWidthPref')
    const { detailsMaxWidth } = await import('../detailsWidthPref')
    sidebarWidth.value = 400
    expect(detailsMaxWidth(2000)).toBe(1200)
    sidebarWidth.value = 288
    expect(detailsMaxWidth(2000)).toBe(1312)
  })
  it('ajusta aos limites', () => {
    expect(clampDetailsWidth(100, 2000)).toBe(300)
    expect(clampDetailsWidth(5000, 1200)).toBe(512)
    expect(clampDetailsWidth(420.6, 2000)).toBe(421)
  })
})
