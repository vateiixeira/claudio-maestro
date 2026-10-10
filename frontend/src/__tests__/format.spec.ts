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

  it('menos de uma hora continua em minutos mesmo depois da meia-noite', () => {
    const justAfterMidnight = new Date(2026, 8, 28, 0, 3, 0)
    expect(formatActivity(at(new Date(2026, 8, 27, 23, 21, 0)), justAfterMidnight)).toBe('há 42 min')
    expect(formatActivity(at(new Date(2026, 8, 27, 22, 0, 0)), justAfterMidnight)).toBe('ontem')
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

describe('formatModelName', () => {
  it('família e versão, sem o prefixo claude', async () => {
    const { formatModelName } = await import('../format')
    expect(formatModelName('claude-sonnet-5-5')).toBe('Sonnet 5.5')
    expect(formatModelName('claude-opus-4-7')).toBe('Opus 4.7')
    expect(formatModelName('claude-sonnet-5')).toBe('Sonnet 5')
  })
  it('ignora o sufixo de data e o de contexto', async () => {
    const { formatModelName } = await import('../format')
    expect(formatModelName('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(formatModelName('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(formatModelName('claude-opus-4-7[1m]')).toBe('Opus 4.7 (1M)')
    expect(formatModelName('opus[1m]')).toBe('Opus (1M)')
  })
  it('versões antigas com o número antes da família', async () => {
    const { formatModelName } = await import('../format')
    expect(formatModelName('claude-3-5-sonnet-20241022')).toBe('Sonnet 3.5')
    expect(formatModelName('claude-3-opus-20240229')).toBe('Opus 3')
  })
  it('apelidos viram só a família', async () => {
    const { formatModelName } = await import('../format')
    expect(formatModelName('sonnet')).toBe('Sonnet')
    expect(formatModelName('opus')).toBe('Opus')
    expect(formatModelName('haiku')).toBe('Haiku')
    expect(formatModelName('Sonnet')).toBe('Sonnet')
  })
  it('modelo desconhecido volta como veio', async () => {
    const { formatModelName } = await import('../format')
    expect(formatModelName('gpt-5')).toBe('gpt-5')
    expect(formatModelName('inherit')).toBe('inherit')
  })
})
