import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentConversations from '../AgentConversations.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 1, main_session_id: 'main' })]
})
afterEach(() => vi.unstubAllGlobals())

const chat = (session_id: string, title: string) => ({ session_id, title, finished: false, created_at: 1, last_activity_at: 2 })

async function mountChats(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({ 'GET /api/agents/1/conversations': () => jsonResponse([chat('main', 'Principal'), chat('s2', 'Revisão')]), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?agente=1&aba=conversa')
  await router.isReady()
  const wrapper = mount(AgentConversations, { props: { agentId: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch, router }
}

describe('AgentConversations', () => {
  it('abre a conversa principal do agente', async () => {
    const { wrapper, router, fetch } = await mountChats({ 'POST /api/agents/1/main': () => jsonResponse({ session_id: 'main' }) })
    await wrapper.get('[data-test="agent-chat-open"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/main')
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/1/main' && init?.method === 'POST')).toBe(true)
  })

  it('lista os outros assuntos sem repetir a principal e abre um deles', async () => {
    const { wrapper, router, fetch } = await mountChats({ 'POST /api/agents/1/conversations': () => jsonResponse({ session_id: 's2' }) })
    const rows = wrapper.findAll('[data-test="agent-chat-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('Revisão')
    await rows[0]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/s2')
    const post = fetch.mock.calls.find(([u]) => u === '/api/agents/1/conversations' && true)
    expect(JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body))).toEqual({ session_id: 's2' })
    expect(post).toBeDefined()
  })

  it('Nova conversa abre um contexto novo', async () => {
    const { wrapper, router, fetch } = await mountChats({ 'POST /api/agents/1/conversations': () => jsonResponse({ session_id: 'novo' }) })
    await wrapper.get('[data-test="agent-chat-new"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/sessions/novo')
    expect(JSON.parse(String(fetch.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body))).toEqual({ new: true })
  })

  it('mostra o erro quando não consegue abrir e fica na tela', async () => {
    const { wrapper, router } = await mountChats({ 'POST /api/agents/1/conversations': () => jsonResponse({ detail: 'A pasta não está disponível.' }, 409) })
    await wrapper.get('[data-test="agent-chat-new"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('A pasta não está disponível.')
    expect(router.currentRoute.value.fullPath).toBe('/agentes/1?agente=1&aba=conversa')
  })

  it('sem conversas diz como começar', async () => {
    const { wrapper } = await mountChats({ 'GET /api/agents/1/conversations': () => jsonResponse([]) })
    expect(wrapper.find('[data-test="agent-chats-empty"]').exists()).toBe(true)
  })

  it('busca entre os assuntos quando são muitos', async () => {
    const { wrapper } = await mountChats({
      'GET /api/agents/1/conversations': () => jsonResponse([chat('main', 'Principal'), ...['Pagamentos', 'Autenticação', 'Clientes', 'Relatórios'].map((t, i) => chat(`c${i}`, t))]),
    })
    await wrapper.get('[data-test="agent-chat-search"]').setValue('pagamentos')
    expect(wrapper.findAll('[data-test="agent-chat-row"]')).toHaveLength(1)
    expect(wrapper.get('[data-test="agent-chat-row"]').text()).toContain('Pagamentos')
  })
})
