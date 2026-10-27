import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TaskActivity from '../TaskActivity.vue'
import { jsonResponse } from '../../../test/factories'
enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())
const event = (id: number) => ({ id, kind: 'item_updated', actor: `Ator ${id}`, created_at: id, data: {} })
it('carrega anteriores e conserva histórico junto de novos eventos após atualização', async () => {
  const fetch = vi.fn(async (_url: string) => jsonResponse({ items: [event(1)], before: 1, has_more: false, limit: 50 }))
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(TaskActivity, { props: { itemId: 7, events: [event(210)], page: { before: 210, has_more: true, limit: 50 } } })
  expect(wrapper.text()).toContain('Atividades recentes')
  expect(wrapper.text()).toContain('Ator 210')
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(fetch.mock.calls[0]?.[0]).toBe('/api/work-items/7/events?before=210&limit=50')
  expect(wrapper.text()).toContain('Ator 1')
  await wrapper.setProps({ events: [event(211)], page: { before: 211, has_more: true, limit: 50 } })
  for (const id of [1, 210, 211]) expect(wrapper.find(`[data-event-id="${id}"]`).exists()).toBe(true)
})
it('resposta de histórico anterior não vaza ao trocar de tarefa', async () => {
  let release!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { release = resolve })))
  const wrapper = mount(TaskActivity, { props: { itemId: 7, events: [event(210)], page: { before: 210, has_more: true, limit: 50 } } })
  await wrapper.get('button').trigger('click')
  await wrapper.setProps({ itemId: 8, events: [event(1000)], page: { before: 1000, has_more: false, limit: 50 } })
  release(jsonResponse({ items: [event(1)], before: 1, has_more: false, limit: 50 })); await flushPromises()
  expect(wrapper.text()).toContain('Ator 1000')
  expect(wrapper.find('[data-event-id="1"]').exists()).toBe(false)
})
