import { describe, expect, it } from 'vitest'
import { formatReset, resetPhrase, severityClass } from '../usageFormat'

const at = (...args: [number, number, number, number, number]) => new Date(...args).getTime()
const unix = (ms: number) => ms / 1000
const NOW = at(2026, 9, 5, 18, 47) // segunda, 05/10/2026 18:47

describe('formatReset', () => {
  it('hoje mostra só a hora', () => {
    expect(formatReset(unix(at(2026, 9, 5, 21, 30)), NOW)).toBe('21:30')
  })
  it('nos próximos 6 dias mostra o dia da semana', () => {
    expect(formatReset(unix(at(2026, 9, 6, 0, 30)), NOW)).toBe('ter 00:30')
    expect(formatReset(unix(at(2026, 9, 10, 9, 5)), NOW)).toBe('sáb 09:05')
    expect(formatReset(unix(at(2026, 9, 11, 19, 0)), NOW)).toBe('dom 19:00')
  })
  it('a partir de 7 dias mostra a data', () => {
    expect(formatReset(unix(at(2026, 9, 12, 19, 0)), NOW)).toBe('12/10 19:00')
  })
  it('horário que já passou mostra só a hora', () => {
    expect(formatReset(unix(at(2026, 9, 5, 9, 0)), NOW)).toBe('09:00')
  })
  it('sem horário fica vazio', () => {
    expect(formatReset(null, NOW)).toBe('')
  })
})

describe('resetPhrase', () => {
  it('usa "às" só quando é só a hora', () => {
    expect(resetPhrase('21:30')).toBe('às 21:30')
    expect(resetPhrase('seg 19:00')).toBe('seg 19:00')
    expect(resetPhrase('12/10 19:00')).toBe('12/10 19:00')
  })
})

describe('severityClass', () => {
  it('mapeia o nível para a cor da barra', () => {
    expect(severityClass('normal')).toBe('bg-primary')
    expect(severityClass('warning')).toBe('bg-secondary')
    expect(severityClass('critical')).toBe('bg-diff-del-fg')
    expect(severityClass('outro')).toBe('bg-primary')
  })
})
