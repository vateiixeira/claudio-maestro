import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarAgents from '../SidebarAgents.vue'
import { createAppRouter } from '../../../router'
import { useSessionsStore } from '../../../stores/sessions'
import { useSpecialistsStore } from '../../../stores/specialists'
import { jsonResponse, makeSession, makeSpecialist, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

async function mountAgents(path = '/inbox') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SidebarAgents, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('seção Agentes da barra lateral', () => {
  it('renders one row per agent with unseen count', async () => {
    const specialists = useSpecialistsStore(pinia)
    specialists.list = [
      makeSpecialist({ id: 1, name: 'Triagem', unseen: 2 }),
      makeSpecialist({ id: 2, slug: 'filmes', name: 'Filmes', unseen: 0 }),
    ]
    const { wrapper } = await mountAgents()
    expect(wrapper.get('[data-test="section-title"]').text()).toBe('Agentes')
    const rows = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('Triagem')
    expect(rows[0]!.find('[data-test="agent-badge"]').exists()).toBe(true)
    expect(rows[0]!.get('[data-test="sidebar-agent-unseen"]').text()).toBe('2')
    expect(rows[1]!.find('[data-test="sidebar-agent-unseen"]').exists()).toBe(false)
  })

  it('soma ao contador os pedidos de ok das sessões do agente, sem contar a principal duas vezes', async () => {
    useSpecialistsStore(pinia).list = [makeSpecialist({ id: 1, name: 'Triagem', unseen: 2, main_session_id: 'main' })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'main', agent_id: 1, pending_kind: 'tool' }), // já entra no `unseen`
      makeSession({ session_id: 'run1', agent_id: 1, pending_kind: 'tool' }),
      makeSession({ session_id: 'run2', agent_id: 1, state: 'awaiting_decision' }),
      makeSession({ session_id: 'run3', agent_id: 1, pending_kind: 'plan', display_state: 'finished' }),
      makeSession({ session_id: 'other', agent_id: 2, pending_kind: 'tool' }),
      makeSession({ session_id: 'plain', pending_kind: 'tool' }),
    ])
    const { wrapper } = await mountAgents()
    expect(wrapper.get('[data-test="sidebar-agent-unseen"]').text()).toBe('4')
  })

  it('disabled agent is muted', async () => {
    useSpecialistsStore(pinia).list = [
      makeSpecialist({ id: 1, name: 'Triagem', enabled: false }),
      makeSpecialist({ id: 2, slug: 'filmes', name: 'Filmes', enabled: true }),
    ]
    const { wrapper } = await mountAgents()
    const [off, on] = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(off!.classes()).toContain('text-fg-subtle')
    expect(on!.classes()).not.toContain('text-fg-subtle')
  })

  it('hidden without agents', async () => {
    const { wrapper } = await mountAgents()
    expect(wrapper.find('[data-test="sidebar-agents"]').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('click opens main conversation', async () => {
    useSpecialistsStore(pinia).list = [makeSpecialist({ id: 7, name: 'Triagem' })]
    const fetch = routeFetch({ 'POST /api/agents/7/main': () => jsonResponse({ session_id: 'conv-7' }) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountAgents()
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe('session')
    expect(router.currentRoute.value.params.id).toBe('conv-7')
  })

  it('confere a conversa principal na API mesmo quando há id em cache', async () => {
    useSpecialistsStore(pinia).list = [makeSpecialist({ id: 7, name: 'Triagem', main_session_id: 'conv-7' })]
    const fetch = routeFetch({ 'POST /api/agents/7/main': () => jsonResponse({ session_id: 'conv-7' }) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountAgents()
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.params.id).toBe('conv-7')
  })

  it('marca a linha do agente quando a rota é a conversa principal dele', async () => {
    useSpecialistsStore(pinia).list = [
      makeSpecialist({ id: 1, name: 'Triagem', main_session_id: 'conv-1' }),
      makeSpecialist({ id: 2, slug: 'filmes', name: 'Filmes', main_session_id: 'conv-2' }),
    ]
    const { wrapper } = await mountAgents('/sessions/conv-2')
    const [a, b] = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(a!.attributes('aria-current')).toBeUndefined()
    expect(b!.attributes('aria-current')).toBe('page')
  })

  it('mostra o erro de rede sem travar a linha', async () => {
    useSpecialistsStore(pinia).list = [makeSpecialist({ id: 7, name: 'Triagem' })]
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/agents/7/main': () => (++calls === 1 ? jsonResponse({ detail: 'A pasta do projeto não está disponível.' }, 409) : jsonResponse({ session_id: 'conv-7' })),
    }))
    const { wrapper, router } = await mountAgents()
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('A pasta do projeto não está disponível.')
    expect(router.currentRoute.value.name).toBe('inbox')
    // a linha continua clicável
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(router.currentRoute.value.params.id).toBe('conv-7')
  })
})
