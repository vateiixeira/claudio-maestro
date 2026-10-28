import { describe, expect, it } from 'vitest'
import { daysLabel, nextFireLabel, scheduleLabel, toggleDay } from '../schedule'

// 2026-10-28 is a Wednesday (ISO day 3).
const wednesdayNoon = new Date(2026, 9, 28, 12, 0)

describe('toggleDay', () => {
  it('liga e desliga um dia mantendo a ordem', () => {
    expect(toggleDay('15', '3')).toBe('135')
    expect(toggleDay('135', '3')).toBe('15')
    expect(toggleDay('', '7')).toBe('7')
  })
})

describe('daysLabel', () => {
  it('resume os dias', () => {
    expect(daysLabel('12345')).toBe('seg–sex')
    expect(daysLabel('1234567')).toBe('todos os dias')
    expect(daysLabel('67')).toBe('sáb, dom')
    expect(daysLabel('135')).toBe('seg, qua, sex')
    expect(daysLabel('2')).toBe('ter')
    expect(daysLabel('1234')).toBe('seg–qui')
    expect(daysLabel('12457')).toBe('seg, ter, qui, sex, dom')
  })
})

describe('scheduleLabel', () => {
  it('junta dias e hora', () => {
    expect(scheduleLabel({ days: '12345', time: '08:00' })).toBe('seg–sex 08:00')
  })
})

describe('nextFireLabel', () => {
  it('sem horários', () => {
    expect(nextFireLabel([], true, wednesdayNoon)).toBe('sem horário')
  })

  it('rotina desligada', () => {
    expect(nextFireLabel([{ days: '1234567', time: '08:00' }], false, wednesdayNoon)).toBe('rotina desligada')
  })

  it('o próximo horário de hoje, se ainda não passou', () => {
    expect(nextFireLabel([{ days: '3', time: '15:30' }], true, wednesdayNoon)).toBe('próximo: qua 15:30')
  })

  it('pula para o próximo dia que casa', () => {
    expect(nextFireLabel([{ days: '12345', time: '08:00' }], true, wednesdayNoon)).toBe('próximo: qui 08:00')
    expect(nextFireLabel([{ days: '1', time: '08:00' }], true, wednesdayNoon)).toBe('próximo: seg 08:00')
  })

  it('escolhe o mais cedo entre vários horários', () => {
    const schedules = [{ days: '3', time: '18:00' }, { days: '3', time: '13:00' }]
    expect(nextFireLabel(schedules, true, wednesdayNoon)).toBe('próximo: qua 13:00')
  })

  it('o mesmo dia da semana na semana seguinte', () => {
    expect(nextFireLabel([{ days: '3', time: '08:00' }], true, wednesdayNoon)).toBe('próximo: qua 08:00')
  })
})
