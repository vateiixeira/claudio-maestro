import { describe, expect, it } from 'vitest'
import { formatActivity, tildePath } from '../format'

describe('tildePath', () => {
  it('troca a pasta pessoal por ~', () => {
    expect(tildePath('/home/vi/dev/loja', '/home/vi')).toBe('~/dev/loja')
    expect(tildePath('/home/vi', '/home/vi')).toBe('~')
    expect(tildePath('/home/vitor/x', '/home/vi')).toBe('/home/vitor/x')
    expect(tildePath('/home/vi/x', null)).toBe('/home/vi/x')
  })
})

describe('formatActivity', () => {
  const now = new Date(2026, 8, 28, 15, 0, 0)
  const at = (d: Date) => Math.floor(d.getTime() / 1000)

  it('usa tempo relativo quando é recente', () => {
    expect(formatActivity(at(new Date(2026, 8, 28, 14, 59, 40)), now)).toBe('agora')
    expect(formatActivity(at(new Date(2026, 8, 28, 14, 56, 0)), now)).toBe('há 4 min')
    expect(formatActivity(at(new Date(2026, 8, 28, 12, 0, 0)), now)).toBe('há 3 h')
  })

  it('usa ontem e depois a data', () => {
    expect(formatActivity(at(new Date(2026, 8, 27, 23, 0, 0)), now)).toBe('ontem')
    expect(formatActivity(at(new Date(2026, 8, 26, 10, 0, 0)), now)).toBe('26 set')
    expect(formatActivity(at(new Date(2025, 11, 3, 10, 0, 0)), now)).toBe('3 dez 2025')
  })
})
