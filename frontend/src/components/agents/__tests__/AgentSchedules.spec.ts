import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import AgentSchedules from '../AgentSchedules.vue'
import { makeSpecialist } from '../../../test/factories'

enableAutoUnmount(afterEach)
const at = (time: string) => makeSpecialist({ schedules: [{ id: 1, days: '12345', time, last_fired_at: null }] })
const times = (w: ReturnType<typeof mount>) => w.findAll<HTMLInputElement>('[data-test="schedule-time"]').map((i) => i.element.value)

describe('AgentSchedules', () => {
  it('sem edição, acompanha o que mudou no servidor', async () => {
    const w = mount(AgentSchedules, { props: { agent: at('08:40'), save: vi.fn() } })
    await w.setProps({ agent: at('10:00') })
    expect(times(w)).toEqual(['10:00'])
  })

  it('com um rascunho editado, a mudança do servidor não o sobrescreve', async () => {
    const w = mount(AgentSchedules, { props: { agent: at('08:40'), save: vi.fn() } })
    await w.get('[data-test="schedule-time"]').setValue('09:15')
    await w.setProps({ agent: at('10:00') })
    expect(times(w)).toEqual(['09:15'])
  })

  it('depois de salvar, o rascunho passa a ser o do servidor', async () => {
    const w = mount(AgentSchedules, { props: { agent: at('08:40'), save: vi.fn() } })
    await w.get('[data-test="schedule-time"]').setValue('09:15')
    await w.setProps({ agent: at('09:15') })
    expect(times(w)).toEqual(['09:15'])
    await w.setProps({ agent: at('11:00') })
    expect(times(w)).toEqual(['11:00'])
  })
})
