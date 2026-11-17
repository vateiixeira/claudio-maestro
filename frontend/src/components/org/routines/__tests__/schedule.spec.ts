import { describe, expect, it } from 'vitest'
import { daysLabel, nextFireLabel, nextSlot, scheduleLabel, scheduleSentence, slotLabel, toggleDay, weekSlots } from '../schedule'

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

describe('agenda em frase', () => {
  // 2026-11-17 is a Tuesday.
  const now = new Date(2026, 10, 17, 10, 40)
  const daily = [{ days: '1234567', time: '07:40' }, { days: '1234567', time: '18:40' }]

  it('nextSlot acha a próxima hora depois de agora', () => {
    expect(nextSlot(daily, now)).toEqual(new Date(2026, 10, 17, 18, 40))
    expect(nextSlot([{ days: '12345', time: '08:40' }], now)).toEqual(new Date(2026, 10, 18, 8, 40))
    expect(nextSlot([{ days: '2', time: '10:40' }], now)).toEqual(new Date(2026, 10, 24, 10, 40))
    expect(nextSlot([], now)).toBeNull()
    expect(nextSlot([{ days: '', time: '08:00' }], now)).toBeNull()
  })

  it('slotLabel diz hoje, amanhã ou o dia da semana', () => {
    expect(slotLabel(new Date(2026, 10, 17, 18, 40), now)).toBe('hoje 18:40')
    expect(slotLabel(new Date(2026, 10, 18, 8, 40), now)).toBe('amanhã 08:40')
    expect(slotLabel(new Date(2026, 10, 20, 8, 40), now)).toBe('sex 08:40')
  })

  it('scheduleSentence escreve a agenda em frase', () => {
    expect(scheduleSentence(daily)).toBe('Todos os dias às 07:40 e às 18:40')
    expect(scheduleSentence([{ days: '12345', time: '08:40' }])).toBe('De segunda a sexta às 08:40')
    expect(scheduleSentence([{ days: '135', time: '09:00' }])).toBe('Segunda, quarta e sexta às 09:00')
    expect(scheduleSentence([{ days: '67', time: '10:00' }])).toBe('Sábado e domingo às 10:00')
    expect(scheduleSentence([{ days: '1', time: '08:00' }, { days: '5', time: '17:00' }])).toBe('Segunda às 08:00; sexta às 17:00')
    expect(scheduleSentence([{ days: '12345', time: '08:40' }, { days: '67', time: '10:00' }])).toBe('De segunda a sexta às 08:40; sábado e domingo às 10:00')
    expect(scheduleSentence([])).toBe('Sem horário')
  })

  it('weekSlots lista as horas de cada dia, de segunda a domingo', () => {
    expect(weekSlots([{ days: '12345', time: '08:40' }])).toEqual([['08:40'], ['08:40'], ['08:40'], ['08:40'], ['08:40'], [], []])
    expect(weekSlots(daily)[1]).toEqual(['07:40', '18:40'])
    expect(weekSlots([{ days: '1', time: '09:00' }, { days: '1', time: '08:00' }, { days: '1', time: '09:00' }])[0]).toEqual(['08:00', '09:00'])
  })
})
