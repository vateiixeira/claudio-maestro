import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import RoutineWeek from '../RoutineWeek.vue'

enableAutoUnmount(afterEach)

// Tuesday, 10:40.
const now = new Date(2026, 10, 17, 10, 40)

function mountWeek(schedules: { days: string; time: string }[], active = true) {
  return mount(RoutineWeek, { props: { schedules, now, active } })
}

describe('RoutineWeek', () => {
  it('mostra sete dias e marca só hoje', () => {
    const w = mountWeek([{ days: '1234567', time: '07:40' }])
    const days = w.findAll('[data-test="routine-week-day"]')
    expect(days.map((d) => d.attributes('data-day'))).toEqual(['1', '2', '3', '4', '5', '6', '7'])
    expect(days.filter((d) => d.attributes('data-today') !== undefined).map((d) => d.attributes('data-day'))).toEqual(['2'])
  })

  it('lista os horários de cada dia e destaca só o próximo', () => {
    const w = mountWeek([{ days: '1234567', time: '07:40' }, { days: '1234567', time: '18:40' }])
    for (const day of w.findAll('[data-test="routine-week-day"]')) {
      expect(day.findAll('[data-test="routine-week-slot"]').map((s) => s.text())).toEqual(['07:40', '18:40'])
    }
    const next = w.findAll('[data-test="routine-week-slot"][data-next="true"]')
    expect(next).toHaveLength(1)
    expect(next[0]!.text()).toBe('18:40')
    expect(next[0]!.element.closest('[data-test="routine-week-day"]')!.getAttribute('data-day')).toBe('2')
  })

  it('o próximo só fica verde quando a rotina roda; senão, tom neutro', () => {
    const slots = [{ days: '1234567', time: '18:40' }]
    const on = mountWeek(slots).get('[data-test="routine-week-slot"][data-next="true"]')
    expect(on.classes().join(' ')).toContain('text-primary-soft')
    const off = mountWeek(slots, false).get('[data-test="routine-week-slot"][data-next="true"]')
    expect(off.classes().join(' ')).not.toContain('primary')
    expect(off.text()).toBe('18:40')
  })

  it('dias sem horário ficam vazios', () => {
    const w = mountWeek([{ days: '135', time: '08:40' }])
    const days = w.findAll('[data-test="routine-week-day"]')
    expect(days[1]!.findAll('[data-test="routine-week-slot"]')).toHaveLength(0)
    expect(days[0]!.findAll('[data-test="routine-week-slot"]')).toHaveLength(1)
  })

  it('sem horários não destaca nada e não quebra', () => {
    const w = mountWeek([])
    expect(w.findAll('[data-test="routine-week-slot"]')).toHaveLength(0)
    expect(w.findAll('[data-test="routine-week-day"]')).toHaveLength(7)
  })

  it('descreve a agenda para leitor de tela', () => {
    const w = mountWeek([{ days: '12345', time: '08:40' }])
    expect(w.get('[data-test="routine-week"]').attributes('aria-label')).toBe('Agenda da semana: de segunda a sexta às 08:40')
  })
})
