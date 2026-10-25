import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, routeFetch } from '../../../test/factories'
import AgentConversations from '../AgentConversations.vue'

enableAutoUnmount(afterEach)
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

it('abre a conversa existente e permite começar outro contexto', async () => {
  const fetch = routeFetch({
    'GET /api/specialists/1/conversations': () => jsonResponse([{ session_id: 's1', title: 'Revisão', finished: false, created_at: 1, last_activity_at: 2 }]),
    'POST /api/specialists/1/conversations': () => jsonResponse({ session_id: 's1' }),
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1')
  const wrapper = mount(AgentConversations, { props: { agentId: 1 }, global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('Revisão')
  await wrapper.get('[data-test="agent-chat-open"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/sessions/s1')
  expect(JSON.parse(String(fetch.mock.calls.find(([url, init]) => url.endsWith('/conversations') && init?.method === 'POST')?.[1]?.body))).toEqual({})
})

it('mantém a lista e mostra erro quando não consegue abrir', async () => {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/specialists/1/conversations': () => jsonResponse([]),
    'POST /api/specialists/1/conversations': () => jsonResponse({ detail: 'A pasta não está disponível.' }, 409),
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1')
  const wrapper = mount(AgentConversations, { props: { agentId: 1 }, global: { plugins: [router] } })
  await flushPromises()
  await wrapper.get('[data-test="agent-chat-new"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('A pasta não está disponível.')
  expect(router.currentRoute.value.fullPath).toBe('/agentes/1')
})
