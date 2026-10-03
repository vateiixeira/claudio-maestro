import { describe, expect, it } from 'vitest'
import { formatActivity, formatElapsedShort, tildePath } from '../format'

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

describe('formatElapsedShort', () => {
  const now = Date.UTC(2026, 9, 2, 12, 0, 0)
  const ago = (s: number) => Math.floor(now / 1000) - s
  it('curto, arredondando para baixo', () => {
    expect(formatElapsedShort(ago(10), now)).toBe('agora')
    expect(formatElapsedShort(ago(-30), now)).toBe('agora')
    expect(formatElapsedShort(ago(60), now)).toBe('1 min')
    expect(formatElapsedShort(ago(3 * 60 + 59), now)).toBe('3 min')
    expect(formatElapsedShort(ago(3599), now)).toBe('59 min')
    expect(formatElapsedShort(ago(3600), now)).toBe('1 h')
    expect(formatElapsedShort(ago(5 * 3600 + 10), now)).toBe('5 h')
    expect(formatElapsedShort(ago(86400), now)).toBe('1 dia')
    expect(formatElapsedShort(ago(3 * 86400 + 5), now)).toBe('3 dias')
  })
})

describe('formatRunningTime', () => {
  it('segundos, minutos com segundos e horas', async () => {
    const { formatRunningTime } = await import('../format')
    expect(formatRunningTime(0)).toBe('0 s')
    expect(formatRunningTime(12)).toBe('12 s')
    expect(formatRunningTime(59.9)).toBe('59 s')
    expect(formatRunningTime(63)).toBe('1 min 3 s')
    expect(formatRunningTime(120)).toBe('2 min')
    expect(formatRunningTime(3599)).toBe('59 min 59 s')
    expect(formatRunningTime(3600)).toBe('1 h')
    expect(formatRunningTime(3600 + 5 * 60 + 9)).toBe('1 h 5 min')
  })
  it('relógio um pouco atrasado não dá tempo negativo', async () => {
    const { formatRunningTime } = await import('../format')
    expect(formatRunningTime(-3)).toBe('0 s')
  })
})
