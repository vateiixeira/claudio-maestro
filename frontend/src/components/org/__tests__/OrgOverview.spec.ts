import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import OrgOverview from '../OrgOverview.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, makeRoutine, makeRun, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
let pinia: Pinia

beforeEach(() => {
  // Tuesday 10:40 local time; only the clock is fake, so the promises of the tests still run.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore().projects = [
    makeProject({ id: 1, name: 'Loja Demo', color: '#4fd1c5' }),
    makeProject({ id: 2, name: 'Docs' }),
    makeProject({ id: 3, name: 'Site' }),
    makeProject({ id: 77, name: 'Sem projeto', path: '/tmp/scratch', kind: 'scratch', position: 99 }),
  ]
  useProjectsStore().loaded = true
  const org = useOrgStore()
  org.loaded = true
  org.agents = [
    makeAgent({ id: 10, slug: 'maestro', name: 'Maestro', description: 'Coordena o trabalho', project_id: 1, reports_to: null }),
    makeAgent({ id: 11, slug: 'triagem', name: 'Triagem', description: 'Separa os chamados', project_id: 1, reports_to: 10, enabled: false, unseen: 4 }),
  ]
  org.runs = {
    10: [],
    11: [makeRun({ id: 3, agent_id: 11, outcome: 'missed' }), makeRun({ id: 2, agent_id: 11, outcome: 'failed' }), makeRun({ id: 1, agent_id: 11, outcome: 'concluded' })],
  }
  org.routines = { 1: [makeRoutine({ agent_id: 11, enabled: true, schedules: [{ id: 1, days: '12345', time: '03:00', last_fired_at: null }] })] }
})

async function mountOverview() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes')
  await router.isReady()
  const wrapper = mount(OrgOverview, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('OrgOverview', () => {
  it('um cartão por projeto com organização, com o resumo dos agentes e das novidades', async () => {
    const { wrapper } = await mountOverview()
    const cards = wrapper.findAll('[data-test="org-overview-project"]')
    expect(cards).toHaveLength(1)
    expect(cards[0]!.attributes('data-project-id')).toBe('1')
    expect(wrapper.get('[data-test="org-overview-meta"]').text()).toBe('2 agentes · 1 desligado')
    expect(wrapper.get('[data-test="org-overview-unseen"]').text()).toBe('4 novidades')
    const head = cards[0]!.get('[data-test="org-project-option"]')
    expect(head.text()).toContain('Loja Demo')
    expect(head.attributes('href')).toBe('/agentes/1')
  })

  it('com um agente ligado só diz 1 agente e não mostra novidades que não há', async () => {
    useOrgStore().agents = [makeAgent({ id: 10, project_id: 1, unseen: 0 })]
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-test="org-overview-meta"]').text()).toBe('1 agente')
    expect(wrapper.find('[data-test="org-overview-unseen"]').exists()).toBe(false)
  })

  it('uma só novidade fica no singular e vários desligados no plural', async () => {
    useOrgStore().agents = [
      makeAgent({ id: 10, project_id: 1, unseen: 1 }),
      makeAgent({ id: 11, slug: 'b', name: 'B', project_id: 1, reports_to: 10, enabled: false }),
      makeAgent({ id: 12, slug: 'c', name: 'C', project_id: 1, reports_to: 10, enabled: false }),
    ]
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-test="org-overview-meta"]').text()).toBe('3 agentes · 2 desligados')
    expect(wrapper.get('[data-test="org-overview-unseen"]').text()).toBe('1 novidade')
  })

  it('lista os agentes na ordem da árvore, cada um com o link para o painel dele', async () => {
    const { wrapper } = await mountOverview()
    const rows = wrapper.findAll('[data-test="org-overview-agent"]')
    expect(rows.map((r) => r.text())).toEqual([expect.stringContaining('Maestro'), expect.stringContaining('Triagem')])
    expect(rows[0]!.attributes('href')).toBe('/agentes/1?agente=10')
    expect(rows[1]!.attributes('href')).toBe('/agentes/1?agente=11')
    expect(rows[0]!.text()).toContain('Coordena o trabalho')
  })

  it('agente sem execuções, sem novidade e sem rotina', async () => {
    const { wrapper } = await mountOverview()
    const row = wrapper.get('[data-test="org-overview-agent"][data-agent-id="10"]')
    expect(row.get('[data-test="org-overview-history"]').text()).toBe('sem execuções')
    expect(row.find('[data-test="run-history"]').exists()).toBe(false)
    expect(row.get('[data-test="org-overview-agent-unseen"]').text()).toBe('nenhuma')
    expect(row.get('[data-test="org-overview-next"]').text()).toBe('sob demanda')
  })

  it('agente desligado mostra o histórico, as novidades e desligado', async () => {
    const { wrapper } = await mountOverview()
    const row = wrapper.get('[data-test="org-overview-agent"][data-agent-id="11"]')
    expect(row.findAll('[data-test="run-history-bar"]')).toHaveLength(3)
    expect(row.get('[data-test="org-overview-agent-unseen"]').text()).toBe('4')
    expect(row.get('[data-test="org-overview-next"]').text()).toBe('desligado')
  })

  it('agente ligado com rotina ligada mostra o próximo horário', async () => {
    useOrgStore().agents = [makeAgent({ id: 10, project_id: 1 }), makeAgent({ id: 11, slug: 'triagem', name: 'Triagem', project_id: 1, reports_to: 10, enabled: true })]
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-agent-id="11"] [data-test="org-overview-next"]').text()).toBe('amanhã 03:00')
  })

  it('rotina desligada não conta como próximo horário', async () => {
    useOrgStore().agents = [makeAgent({ id: 10, project_id: 1 }), makeAgent({ id: 11, slug: 'triagem', name: 'Triagem', project_id: 1, reports_to: 10 })]
    useOrgStore().routines = { 1: [makeRoutine({ agent_id: 11, enabled: false, schedules: [{ id: 1, days: '1234567', time: '18:40', last_fired_at: null }] })] }
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-agent-id="11"] [data-test="org-overview-next"]').text()).toBe('sob demanda')
  })

  it('projetos sem organização ficam numa grade com Criar e o link para o projeto', async () => {
    const { wrapper } = await mountOverview()
    const options = wrapper.get('[data-test="org-overview-without"]').findAll('[data-test="org-project-option"]')
    expect(options.map((o) => o.text())).toEqual([expect.stringContaining('Docs'), expect.stringContaining('Site')])
    expect(options.map((o) => o.text().includes('Criar'))).toEqual([true, true])
    expect(options.map((o) => o.attributes('href'))).toEqual(['/agentes/2', '/agentes/3'])
  })

  it('os cabeçalhos das duas listas contam os projetos', async () => {
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-test="org-overview-with"] [data-test="group-header-count"]').text()).toBe('1')
    expect(wrapper.get('[data-test="org-overview-without"] [data-test="group-header-count"]').text()).toBe('2')
  })

  it('o projeto embutido não aparece em nenhuma lista', async () => {
    const { wrapper } = await mountOverview()
    expect(wrapper.text()).not.toContain('Sem projeto')
    useOrgStore().agents = [...useOrgStore().agents, makeAgent({ id: 20, slug: 'x', name: 'Solto', project_id: 77 })]
    await flushPromises()
    expect(wrapper.text()).not.toContain('Solto')
    expect(wrapper.findAll('[data-test="org-project-option"]')).toHaveLength(3)
  })

  it('sem projetos sem organização não mostra a lista dela', async () => {
    useProjectsStore().projects = [makeProject({ id: 1, name: 'Loja Demo' })]
    const { wrapper } = await mountOverview()
    expect(wrapper.find('[data-test="org-overview-without"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="org-overview-with"]').exists()).toBe(true)
  })

  it('lê as rotinas do projeto e as execuções de cada agente dele, uma vez só', async () => {
    const org = useOrgStore()
    org.runs = {}
    org.routines = {}
    const fetch = routeFetch({
      'GET /api/routines?project_id=1': () => jsonResponse([]),
      'GET /api/agents/10/runs?limit=50': () => jsonResponse([]),
      'GET /api/agents/11/runs?limit=50': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    await mountOverview()
    const urls = fetch.mock.calls.map((c) => c[0])
    expect(urls.filter((u) => u === '/api/routines?project_id=1')).toHaveLength(1)
    expect(urls.filter((u) => u === '/api/agents/10/runs?limit=50')).toHaveLength(1)
    expect(urls.filter((u) => u === '/api/agents/11/runs?limit=50')).toHaveLength(1)
    expect(urls.some((u) => String(u).includes('project_id=2'))).toBe(false)
  })

  it('enquanto os agentes não chegam, avisa que está carregando', async () => {
    useOrgStore().loaded = false
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[role="status"]').text()).toContain('Carregando agentes')
    expect(wrapper.find('[data-test="org-overview-without"]').exists()).toBe(false)
  })

  it('com erro na carga dos agentes mostra o erro, não chama os projetos de sem organização e tenta de novo', async () => {
    const org = useOrgStore()
    org.agents = []
    org.error = 'Sem conexão'
    const fetch = routeFetch({ 'GET /api/agents': () => jsonResponse([]) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-test="org-overview-error"]').text()).toContain('Sem conexão')
    expect(wrapper.find('[data-test="org-overview-without"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Criar')
    await wrapper.get('[data-test="org-overview-retry"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some((c) => c[0] === '/api/agents')).toBe(true)
    expect(wrapper.find('[data-test="org-overview-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="org-overview-without"]').exists()).toBe(true)
  })

  it('o erro de carga também aparece antes de a carga terminar de marcar loaded', async () => {
    useOrgStore().loaded = false
    useOrgStore().error = 'Falhou'
    const { wrapper } = await mountOverview()
    expect(wrapper.get('[data-test="org-overview-error"]').text()).toContain('Falhou')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('montada sem a carga dos agentes ter começado, pede os agentes', async () => {
    const org = useOrgStore()
    org.loaded = false
    org.error = null
    org.agents = []
    const fetch = routeFetch({ 'GET /api/agents': () => jsonResponse([makeAgent({ id: 10, project_id: 1 })]) })
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountOverview()
    expect(fetch.mock.calls.filter((c) => c[0] === '/api/agents')).toHaveLength(1)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="org-overview-project"]')).toHaveLength(1)
  })
})
