import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarAgents from '../SidebarAgents.vue'
import { collapsed, setSectionOpened } from '../../../sidebarCollapse'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  collapsed.value = { project: [], group: [], section: [] }
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 2, name: 'API' })]
})
afterEach(() => vi.unstubAllGlobals())

async function mountAgents(path = '/inbox', expanded = true) {
  if (expanded) setSectionOpened('agents', true)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SidebarAgents, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('seção Agentes da barra lateral', () => {
  it('começa recolhida, preserva novidades e lembra a expansão sem abrir conversas', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, unseen: 3 }), makeAgent({ id: 2, slug: 'dev', unseen: 2 })]
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountAgents('/inbox', false)
    const toggle = wrapper.get('[data-test="sidebar-agents-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toContain('2 agentes')
    expect(toggle.text()).toContain('5 novidades')
    expect(wrapper.find('[data-test="sidebar-agent-row"]').exists()).toBe(false)
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('[data-test="sidebar-agent-row"]')).toHaveLength(2)
    expect(JSON.parse(localStorage.getItem('maestro:sidebar-collapsed')!).section).toContain('+agents')
    expect(fetch).not.toHaveBeenCalled()
    await toggle.trigger('click')
    expect(wrapper.find('[data-test="sidebar-agent-row"]').exists()).toBe(false)
  })

  it('agrupa por projeto e abre a conversa principal', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'CTO da loja', project_id: 1, unseen: 2 }),
      makeAgent({ id: 2, slug: 'dev', name: 'Dev', project_id: 1, reports_to: 1 }),
      makeAgent({ id: 3, slug: 'api', name: 'CTO da API', project_id: 2 }),
    ]
    const fetch = routeFetch({ 'POST /api/agents/3/main': () => jsonResponse({ session_id: 'conv-3' }) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountAgents()
    expect(wrapper.get('[data-test="section-title"]').text()).toBe('Agentes')
    expect(wrapper.findAll('[data-test="sidebar-agent-project"]').map((h) => h.text())).toEqual(['Loja', 'API'])
    const rows = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(rows.map((r) => r.get('[data-test="sidebar-agent-name"]').text())).toEqual(['CTO da loja', 'Dev', 'CTO da API'])
    expect(rows[0]!.get('[data-test="sidebar-agent-unseen"]').text()).toBe('2')
    expect(rows[1]!.find('[data-test="sidebar-agent-unseen"]').exists()).toBe(false)
    expect(rows[0]!.find('[data-test="agent-state"]').exists()).toBe(true)

    await rows[2]!.trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe('session')
    expect(router.currentRoute.value.params.id).toBe('conv-3')
  })

  it('agente desligado fica esmaecido', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'Parado', enabled: false }),
      makeAgent({ id: 2, slug: 'b', name: 'Ativo', reports_to: 1 }),
    ]
    const { wrapper } = await mountAgents()
    // Ordered by name inside the project.
    const [on, off] = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(off!.classes()).toContain('text-fg-subtle')
    expect(on!.classes()).not.toContain('text-fg-subtle')
  })

  it('some sem agentes', async () => {
    const { wrapper } = await mountAgents()
    expect(wrapper.find('[data-test="sidebar-agents"]').exists()).toBe(false)
  })

  it('marca a linha do agente quando a rota é a conversa principal dele', async () => {
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'A', main_session_id: 'conv-1' }),
      makeAgent({ id: 2, slug: 'b', name: 'B', main_session_id: 'conv-2' }),
    ]
    const { wrapper } = await mountAgents('/sessions/conv-2')
    const [a, b] = wrapper.findAll('[data-test="sidebar-agent-row"]')
    expect(a!.attributes('aria-current')).toBeUndefined()
    expect(b!.attributes('aria-current')).toBe('page')
  })

  it('mostra o erro de rede sem travar a linha', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 7, name: 'Triagem' })]
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/agents/7/main': () => (++calls === 1 ? jsonResponse({ detail: 'A pasta do projeto não está disponível.' }, 409) : jsonResponse({ session_id: 'conv-7' })),
    }))
    const { wrapper, router } = await mountAgents()
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('A pasta do projeto não está disponível.')
    expect(router.currentRoute.value.name).toBe('inbox')
    await wrapper.get('[data-test="sidebar-agent-row"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(router.currentRoute.value.params.id).toBe('conv-7')
  })
})
