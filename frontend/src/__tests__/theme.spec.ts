/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const html = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../index.html'), 'utf8')

const root = () => document.documentElement
beforeEach(() => {
  localStorage.clear()
  vi.resetModules()
  root().removeAttribute('data-theme')
})
afterEach(() => {
  vi.restoreAllMocks()
  root().removeAttribute('data-theme')
})

describe('temas da interface', () => {
  it('lista os oito temas, o Maestro primeiro e como padrão', async () => {
    const mod = await import('../theme')
    expect(mod.THEMES.map((t) => t.id)).toEqual([
      'maestro',
      'dracula',
      'monokai-pro',
      'monokai-machine',
      'monokai-octagon',
      'monokai-ristretto',
      'monokai-spectrum',
      'monokai-classic',
    ])
    expect(mod.THEME_DEFAULT).toBe('maestro')
    for (const t of mod.THEMES) {
      expect(t.label.length, t.id).toBeGreaterThan(0)
    }
  })

  it('começa no Maestro quando nada foi salvo', async () => {
    const mod = await import('../theme')
    expect(mod.readTheme()).toBe('maestro')
    expect(mod.theme.value).toBe('maestro')
  })

  it('relê um tema salvo', async () => {
    localStorage.setItem('maestro:theme', 'dracula')
    const mod = await import('../theme')
    expect(mod.readTheme()).toBe('dracula')
    expect(mod.theme.value).toBe('dracula')
  })

  it('ignora um id salvo que não é um tema', async () => {
    const mod = await import('../theme')
    for (const bad of ['', 'monokai', 'DRACULA', '{"a":1}', 'maestro ']) {
      localStorage.setItem('maestro:theme', bad)
      expect(mod.readTheme(), bad).toBe('maestro')
    }
  })

  it('cai no padrão quando o storage lança exceção ao ler', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    const mod = await import('../theme')
    expect(mod.readTheme()).toBe('maestro')
    expect(mod.theme.value).toBe('maestro')
  })

  it('applyTheme grava data-theme no html, sem salvar', async () => {
    const mod = await import('../theme')
    mod.applyTheme('monokai-pro')
    expect(root().getAttribute('data-theme')).toBe('monokai-pro')
    expect(localStorage.getItem('maestro:theme')).toBeNull()
  })

  it('applyTheme do padrão tira o data-theme', async () => {
    const mod = await import('../theme')
    mod.applyTheme('dracula')
    mod.applyTheme('maestro')
    expect(root().hasAttribute('data-theme')).toBe(false)
  })

  it('setTheme atualiza o ref, aplica no html e salva', async () => {
    const mod = await import('../theme')
    mod.setTheme('monokai-octagon')
    expect(mod.theme.value).toBe('monokai-octagon')
    expect(root().getAttribute('data-theme')).toBe('monokai-octagon')
    expect(localStorage.getItem('maestro:theme')).toBe('monokai-octagon')
  })

  it('setTheme("maestro") volta ao padrão e salva', async () => {
    const mod = await import('../theme')
    mod.setTheme('dracula')
    mod.setTheme('maestro')
    expect(mod.theme.value).toBe('maestro')
    expect(root().hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('maestro:theme')).toBe('maestro')
  })

  it('setTheme ignora um id desconhecido', async () => {
    const mod = await import('../theme')
    mod.setTheme('dracula')
    mod.setTheme('nao-existe')
    expect(mod.theme.value).toBe('dracula')
    expect(root().getAttribute('data-theme')).toBe('dracula')
    expect(localStorage.getItem('maestro:theme')).toBe('dracula')
  })

  it('setTheme funciona mesmo quando salvar lança exceção', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('cheio')
    })
    const mod = await import('../theme')
    expect(() => mod.setTheme('dracula')).not.toThrow()
    expect(mod.theme.value).toBe('dracula')
    expect(root().getAttribute('data-theme')).toBe('dracula')
  })
})

describe('script de boot do index.html', () => {
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? ''
  const run = () => new Function(script)()

  it('existe um script inline que lê maestro:theme', () => {
    expect(script).toContain('maestro:theme')
  })

  it('aplica o tema salvo antes de o app carregar', () => {
    localStorage.setItem('maestro:theme', 'monokai-ristretto')
    run()
    expect(root().getAttribute('data-theme')).toBe('monokai-ristretto')
  })

  it('não aplica nada para um id desconhecido, para o padrão ou sem valor', () => {
    for (const value of ['nao-existe', 'maestro', null]) {
      root().removeAttribute('data-theme')
      localStorage.clear()
      if (value !== null) localStorage.setItem('maestro:theme', value)
      run()
      expect(root().hasAttribute('data-theme'), String(value)).toBe(false)
    }
  })

  it('não quebra quando o storage lança exceção', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    expect(run).not.toThrow()
    expect(root().hasAttribute('data-theme')).toBe(false)
  })

  it('conhece exatamente os ids dos temas novos de theme.ts', async () => {
    const mod = await import('../theme')
    const ids = script.match(/\/\^\(([\w|-]+)\)\$\//)?.[1].split('|') ?? []
    expect(ids.sort()).toEqual(mod.THEMES.map((t) => t.id).filter((id) => id !== 'maestro').sort())
  })
})
