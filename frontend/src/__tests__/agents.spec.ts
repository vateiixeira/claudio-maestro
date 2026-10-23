import { describe, expect, it } from 'vitest'
import { ALWAYS_DEFAULTS, OUTWARD_DEFAULTS, nextRunLabel, slugify, toggleDay } from '../agents'

// 2026-10-26 is a Monday.
const monday = (h: number, m = 0) => new Date(2026, 9, 26, h, m)
const sched = (days: string, time: string) => ({ id: 1, days, time, last_fired_at: null })

describe('nextRunLabel', () => {
  it('mostra o próximo horário com o dia da semana', () => {
    expect(nextRunLabel([sched('1234567', '08:40')], true, monday(7))).toBe('próximo: seg 08:40')
  })

  it('passa para o dia seguinte quando o horário de hoje já passou', () => {
    expect(nextRunLabel([sched('1234567', '08:40')], true, monday(9))).toBe('próximo: ter 08:40')
  })

  it('escolhe o menor entre vários horários e pula dias não marcados', () => {
    const list = [sched('3', '10:00'), sched('5', '07:15')]
    expect(nextRunLabel(list, true, monday(9))).toBe('próximo: qua 10:00')
  })

  it('volta à mesma segunda quando só ela está marcada e já passou', () => {
    expect(nextRunLabel([sched('1', '08:40')], true, monday(9))).toBe('próximo: seg 08:40')
  })

  it('diz "sem horário" quando não há horários', () => {
    expect(nextRunLabel([], true, monday(9))).toBe('sem horário')
  })

  it('diz que os horários estão desligados quando o interruptor está off', () => {
    expect(nextRunLabel([sched('1', '08:40')], false, monday(9))).toBe('horários desligados')
  })
})

describe('slugify', () => {
  it('sugere o identificador a partir do nome', () => {
    expect(slugify('Agente do Sentry')).toBe('agente-do-sentry')
    expect(slugify('  Revisão de PRs!! ')).toBe('revisao-de-prs')
    expect(slugify('---a--b---')).toBe('a-b')
  })

  it('corta no limite do backend sem terminar em hífen', () => {
    const slug = slugify('a'.repeat(39) + ' b')
    expect(slug.length).toBeLessThanOrEqual(40)
    expect(slug.endsWith('-')).toBe(false)
  })

  it('devolve vazio quando não sobra nada', () => {
    expect(slugify('!!!')).toBe('')
  })
})

describe('toggleDay', () => {
  it('liga e desliga um dia mantendo a ordem', () => {
    expect(toggleDay('135', '2')).toBe('1235')
    expect(toggleDay('1235', '3')).toBe('125')
  })
})

describe('padrões de fábrica', () => {
  it('espelham os do backend', () => {
    expect(OUTWARD_DEFAULTS).toContain('git push')
    expect(ALWAYS_DEFAULTS).toEqual(['gh pr merge'])
  })
})
