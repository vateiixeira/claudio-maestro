import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, routeFetch, makeSpecialist, makeSpecialistRun } from '../../../test/factories'
import { useSpecialistsStore } from '../../../stores/specialists'
import AgentChatQueue from '../AgentChatQueue.vue'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
it('mostra a fila pausada após recarregar e cancela só a mensagem desta conversa', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const run = makeSpecialistRun({ id: 3, session_id: 's1', outcome: 'queued', message: true })
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/messages?session_id=s1': () => jsonResponse([{ id: 3, text: 'Mensagem em espera' }]),
    'GET /api/specialists/1/runs?limit=50': () => jsonResponse([run, makeSpecialistRun({ id: 4, session_id: 'other', outcome: 'queued', message: true })]),
    'POST /api/specialists/1/runs/3/cancel': () => jsonResponse({ ...run, outcome: 'cancelled' }),
  }))
  useSpecialistsStore().list = [makeSpecialist({ queue_paused: true })]
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const wrapper = mount(AgentChatQueue, { props: { agentId: 1, sessionId: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('Fila pausada')
  expect(wrapper.text()).toContain('Mensagem em espera')
  expect(wrapper.findAll('[data-test="chat-queued-message"]')).toHaveLength(1)
  await wrapper.get('[data-test="chat-queue-cancel"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-test="chat-queued-message"]')).toHaveLength(0)
})
