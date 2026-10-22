import { describe, expect, it } from 'vitest'
import { contextLayout } from '../contextLayout'
import type { ContextBreakdown, ContextCategory } from '../types/api'

const used = (name: string, tokens: number): ContextCategory => ({ name, tokens, kind: 'used' })

// The print the design was drawn from: 8 used categories, buffer, free space and 2 deferred; window of 400k.
const PRINT: ContextBreakdown = {
  model: 'claude-opus-5-5',
  total_tokens: 85147,
  max_tokens: 400000,
  percent: 21.3,
  categories: [
    used('Messages', 35760),
    used('System tools', 15900),
    used('MCP tools', 11600),
    used('Skills', 10000),
    used('System prompt', 7700),
    used('Memory files', 2100),
    used('Custom agents', 1300),
    used('MCP server instructions', 787),
    { name: 'Autocompact buffer', tokens: 33000, kind: 'buffer' },
    { name: 'Free space', tokens: 281853, kind: 'free' },
    { name: 'MCP tools (deferred)', tokens: 80300, kind: 'deferred' },
    { name: 'System tools (deferred)', tokens: 23800, kind: 'deferred' },
  ],
  mcp_tools: [
    { name: 'smart_search', server: 'claude-mem', tokens: 1900, loaded: true },
    { name: 'search_files', server: 'Google Drive', tokens: 1200, loaded: true },
    { name: 'batch', server: 'Claude Docs', tokens: 900, loaded: false },
  ],
  memory_files: [{ path: '/home/vi/.claude/CLAUDE.md', tokens: 900 }, { path: '/home/vi/dev/x/CLAUDE.md', tokens: 700 }],
  agents: [{ name: 'implementer', tokens: 200 }],
  skills: [{ name: 'superpowers:brainstorming', tokens: 400 }, { name: 'claude-api', tokens: 300 }],
}

describe('contextLayout: barra', () => {
  it('colore as 4 maiores e junta o resto em Outros quando passa de 6 segmentos', () => {
    const { segments } = contextLayout(PRINT)
    expect(segments.map((s) => s.label)).toEqual(['Messages', 'System tools', 'MCP tools', 'Skills', 'Outros', 'Autocompact buffer'])
    expect(segments[4].tokens).toBe(7700 + 2100 + 1300 + 787)
    expect(segments.slice(0, 4).map((s) => s.color)).toEqual([
      'var(--color-type-command)', 'var(--color-secondary-soft)', 'var(--color-type-file)', 'var(--color-type-think)',
    ])
    expect(segments[4].color).toBe('var(--color-fg-subtle)')
    expect(segments[5].color).toBe('var(--color-line-strong)')
  })

  it('sem agrupar quando cabe em 6', () => {
    const { segments } = contextLayout({
      ...PRINT,
      categories: [
        used('Messages', 1000), used('System tools', 500), used('Skills', 100),
        { name: 'Autocompact buffer', tokens: 200, kind: 'buffer' },
      ],
    })
    expect(segments.map((s) => s.label)).toEqual(['Messages', 'System tools', 'Skills', 'Autocompact buffer'])
    expect(segments.map((s) => s.label)).not.toContain('Outros')
  })

  it('o limite é 6 incluindo o buffer: 5 usadas e buffer não agrupam, 6 usadas e buffer agrupam', () => {
    const names = ['A', 'B', 'C', 'D', 'E', 'F']
    const buffer: ContextCategory = { name: 'Autocompact buffer', tokens: 10, kind: 'buffer' }
    const five = contextLayout({ ...PRINT, categories: [...names.slice(0, 5).map((n) => used(n, 100)), buffer] })
    expect(five.segments.map((s) => s.label)).toEqual(['A', 'B', 'C', 'D', 'E', 'Autocompact buffer'])
    const six = contextLayout({ ...PRINT, categories: [...names.map((n) => used(n, 100)), buffer] })
    expect(six.segments.map((s) => s.label)).toEqual(['A', 'B', 'C', 'D', 'Outros', 'Autocompact buffer'])
    expect(six.segments[4].tokens).toBe(200)
  })

  it('sem buffer os extras são 0: 5 usadas cabem na paleta, 6 e 7 agrupam as 5 primeiras coloridas', () => {
    const five = contextLayout({ ...PRINT, categories: 'ABCDE'.split('').map((n) => used(n, 100)) })
    expect(five.segments.map((s) => s.label)).toEqual(['A', 'B', 'C', 'D', 'E'])
    expect(five.segments[4].color).toBe('var(--color-type-agent)')
    const six = contextLayout({ ...PRINT, categories: 'ABCDEF'.split('').map((n) => used(n, 100)) })
    expect(six.segments.map((s) => s.label)).toEqual(['A', 'B', 'C', 'D', 'E', 'Outros'])
    expect(six.segments[4].color).toBe('var(--color-type-agent)')
    expect(six.segments[5]).toMatchObject({ tokens: 100, color: 'var(--color-fg-subtle)' })
    const seven = contextLayout({ ...PRINT, categories: 'ABCDEFG'.split('').map((n) => used(n, 100)) })
    expect(seven.segments.map((s) => s.label)).toEqual(['A', 'B', 'C', 'D', 'E', 'Outros'])
    expect(seven.segments[5].tokens).toBe(200)
  })

  it('6 usadas sem buffer: nenhum segmento nem linha fica sem cor', () => {
    const { segments, rows } = contextLayout({ ...PRINT, categories: 'ABCDEF'.split('').map((n) => used(n, 100)) })
    expect(segments.every((s) => typeof s.color === 'string' && s.color.startsWith('var(--color-'))).toBe(true)
    expect(rows.every((r) => typeof r.color === 'string' && r.color.startsWith('var(--color-'))).toBe(true)
    expect(rows.map((r) => r.color)).toEqual([
      'var(--color-type-command)', 'var(--color-secondary-soft)', 'var(--color-type-file)',
      'var(--color-type-think)', 'var(--color-type-agent)', 'var(--color-fg-subtle)',
    ])
  })

  it('largura é tokens sobre a janela', () => {
    const { segments } = contextLayout(PRINT)
    expect(segments[0].width).toBeCloseTo(8.94, 5)
    expect(segments[5].width).toBeCloseTo(8.25, 5)
  })

  it('acima do limite a soma das larguras não passa de 100 e nada fica negativo', () => {
    const { segments, rows } = contextLayout({
      ...PRINT,
      total_tokens: 483000,
      categories: [used('Messages', 450000), { name: 'Autocompact buffer', tokens: 33000, kind: 'buffer' }],
    })
    expect(segments.reduce((sum, s) => sum + s.width, 0)).toBeLessThanOrEqual(100 + 1e-9)
    expect(segments.every((s) => s.width >= 0)).toBe(true)
    expect(rows.find((r) => r.label === 'Messages')!.percentText).toBe('112,5%')
  })

  it('categorias com 0 token ficam de fora', () => {
    const { segments, rows } = contextLayout({ ...PRINT, categories: [used('Messages', 100), used('Skills', 0)] })
    expect(segments.map((s) => s.label)).toEqual(['Messages'])
    expect(rows.map((r) => r.label)).toEqual(['Messages'])
  })
})

describe('contextLayout: linhas', () => {
  it('linhas na ordem do backend, Free space vira Espaço livre e deferred com —', () => {
    const { rows } = contextLayout(PRINT)
    expect(rows.map((r) => r.label)).toEqual([
      'Messages', 'System tools', 'MCP tools', 'Skills', 'System prompt', 'Memory files', 'Custom agents',
      'MCP server instructions', 'Autocompact buffer', 'Espaço livre', 'MCP tools (deferred)', 'System tools (deferred)',
    ])
    expect(rows.find((r) => r.key.startsWith('free'))!.label).toBe('Espaço livre')
    expect(rows.find((r) => r.label === 'Messages')!.percentText).toBe('8,9%')
    expect(rows.find((r) => r.label === 'MCP tools (deferred)')!).toMatchObject({ percentText: '—', muted: true })
    expect(rows.find((r) => r.label === 'Messages')!.muted).toBe(false)
    expect(rows.find((r) => r.label === 'Espaço livre')!.muted).toBe(false)
    expect(rows.find((r) => r.label === 'Espaço livre')!.percentText).toBe('70,5%')
  })

  it('cores das linhas: segmento a que pertencem; agrupadas em Outros; buffer, livre e deferred à parte', () => {
    const { rows } = contextLayout(PRINT)
    const color = (label: string) => rows.find((r) => r.label === label)!.color
    expect(color('Messages')).toBe('var(--color-type-command)')
    expect(color('Skills')).toBe('var(--color-type-think)')
    expect(color('System prompt')).toBe('var(--color-fg-subtle)')
    expect(color('Custom agents')).toBe('var(--color-fg-subtle)')
    expect(color('Autocompact buffer')).toBe('var(--color-line-strong)')
    expect(color('Espaço livre')).toBe('var(--color-elevated)')
    expect(color('MCP tools (deferred)')).toBe('var(--color-elevated)')
  })

  it('chaves das linhas são únicas', () => {
    const keys = contextLayout(PRINT).rows.map((r) => r.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('sublistas: MCP tools só carregadas, deferred só não carregadas, Skills, Memory files, Custom agents', () => {
    const { rows } = contextLayout(PRINT)
    const details = (label: string) => rows.find((r) => r.label === label)!.details
    expect(details('MCP tools')).toEqual([
      { label: 'claude-mem · smart_search', tokens: 1900 },
      { label: 'Google Drive · search_files', tokens: 1200 },
    ])
    expect(details('MCP tools (deferred)')).toEqual([{ label: 'Claude Docs · batch', tokens: 900 }])
    expect(details('Skills')).toEqual([
      { label: 'superpowers:brainstorming', tokens: 400 },
      { label: 'claude-api', tokens: 300 },
    ])
    expect(details('Memory files')).toEqual([
      { label: '/home/vi/.claude/CLAUDE.md', tokens: 900 },
      { label: '/home/vi/dev/x/CLAUDE.md', tokens: 700 },
    ])
    expect(details('Custom agents')).toEqual([{ label: 'implementer', tokens: 200 }])
  })

  it('linhas sem detalhe ou com lista vazia ficam com details null', () => {
    const { rows } = contextLayout({ ...PRINT, skills: [] })
    const details = (label: string) => rows.find((r) => r.label === label)!.details
    expect(details('System prompt')).toBeNull()
    expect(details('Messages')).toBeNull()
    expect(details('Espaço livre')).toBeNull()
    expect(details('Skills')).toBeNull()
  })
})
