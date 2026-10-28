import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ScheduleEditor from '../ScheduleEditor.vue'

enableAutoUnmount(afterEach)

describe('ScheduleEditor', () => {
  it('sem horários, explica e deixa adicionar', async () => {
    const w = mount(ScheduleEditor, { props: { modelValue: [] } })
    expect(w.text()).toContain('Sem horários')
    await w.get('[data-test="schedule-add"]').trigger('click')
    expect(w.emitted('update:modelValue')![0]).toEqual([[{ days: '12345', time: '09:00' }]])
  })

  it('alterna dias com aria-pressed e edita a hora', async () => {
    const w = mount(ScheduleEditor, { props: { modelValue: [{ days: '12345', time: '08:00' }] } })
    const days = w.findAll('[data-test="day"]')
    expect(days).toHaveLength(7)
    expect(days.map((d) => d.attributes('aria-pressed'))).toEqual(['true', 'true', 'true', 'true', 'true', 'false', 'false'])
    await days[5]!.trigger('click')
    expect(w.emitted('update:modelValue')![0]).toEqual([[{ days: '123456', time: '08:00' }]])
    await w.get('[data-test="schedule-time"]').setValue('09:15')
    expect(w.emitted('update:modelValue')![1]).toEqual([[{ days: '12345', time: '09:15' }]])
  })

  it('remove uma linha', async () => {
    const w = mount(ScheduleEditor, {
      props: { modelValue: [{ days: '1', time: '08:00' }, { days: '2', time: '09:00' }] },
    })
    await w.findAll('[data-test="schedule-remove"]')[0]!.trigger('click')
    expect(w.emitted('update:modelValue')![0]).toEqual([[{ days: '2', time: '09:00' }]])
  })

  it('para de adicionar no limite de 50 horários', async () => {
    const rows = Array.from({ length: 50 }, (_, i) => ({ days: '1', time: `${String(i % 24).padStart(2, '0')}:00` }))
    const w = mount(ScheduleEditor, { props: { modelValue: rows } })
    expect(w.get('[data-test="schedule-add"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-test="schedule-limit"]').text()).toContain('50')
    await w.get('[data-test="schedule-add"]').trigger('click')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})
