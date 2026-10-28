import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import RunsTab from '../RunsTab.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeRun, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [
    makeAgent({ id: 1, slug: 'cto', name: 'CTO' }),
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 }),
    makeAgent({ id: 3, slug: 'outro', name: 'De outro projeto', project_id: 2 }),
  ]
})

const t = 1_790_000_000
const cto = [
  makeRun({ id: 1, agent_id: 1, started_at: t + 100, ended_at: t + 160, outcome: 'concluded' }),
  makeRun({ id: 2, agent_id: 1, started_at: t + 300, ended_at: t + 330, outcome: 'failed', reason: 'Quebrou' }),
]
const dev = [
  makeRun({ id: 3, agent_id: 2, started_at: t + 200, ended_at: t + 260, outcome: 'concluded' }),
  makeRun({ id: 4, agent_id: 2, started_at: t + 400, ended_at: null, outcome: 'running' }),
]

async function mountTab(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({
    'GET /api/agents/1/runs?limit=50': () => jsonResponse(cto),
    'GET /api/agents/2/runs?limit=50': () => jsonResponse(dev),
    ...handlers,
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?aba=execucoes')
  await router.isReady()
  const w = mount(RunsTab, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { w, fetch }
}

const ids = (w: ReturnType<typeof mount>) => w.findAll('[data-test="run-row"]').map((r) => r.attributes('data-run-id'))

describe('RunsTab', () => {
  it('mantém o data-test raiz e a prop da casca', async () => {
    const { w } = await mountTab()
    expect(w.attributes('data-test')).toBe('runs-tab')
    expect(w.attributes('data-project-id')).toBe('1')
  })

  it('junta execuções de vários agentes em ordem', async () => {
    const { w, fetch } = await mountTab()
    expect(ids(w)).toEqual(['4', '2', '3', '1'])
    const names = w.findAll('[data-test="run-agent"]').map((a) => a.text())
    expect(names).toEqual(['Dev', 'CTO', 'Dev', 'CTO'])
    // The agent of another project is not asked.
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/agents/3/'))).toBe(false)
  })

  it('filtra por agente', async () => {
    const { w } = await mountTab()
    await w.get('[data-test="runs-agent-filter"]').setValue('2')
    expect(ids(w)).toEqual(['4', '3'])
    await w.get('[data-test="runs-agent-filter"]').setValue('')
    expect(ids(w)).toEqual(['4', '2', '3', '1'])
  })

  it('o filtro Problemas mantém falhou, esperando, perdida e pulada e tira concluída e rodando', async () => {
    const extra = [
      makeRun({ id: 5, agent_id: 1, started_at: t + 500, ended_at: null, outcome: 'waiting' }),
      makeRun({ id: 6, agent_id: 1, started_at: t + 600, ended_at: t + 600, outcome: 'skipped' }),
      makeRun({ id: 7, agent_id: 1, started_at: t + 700, ended_at: t + 700, outcome: 'missed' }),
      makeRun({ id: 8, agent_id: 1, started_at: t + 800, ended_at: t + 810, outcome: 'cancelled' }),
    ]
    const { w } = await mountTab({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([...cto, ...extra]) })
    const toggle = w.get('[data-test="runs-filter-problems"]')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(ids(w)).toEqual(['8', '7', '6', '5', '4', '2', '3', '1'])
    await toggle.trigger('click')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(ids(w)).toEqual(['7', '6', '5', '2'])
    await w.get('[data-test="runs-agent-filter"]').setValue('2')
    expect(w.find('[data-test="run-row"]').exists()).toBe(false)
    expect(w.get('[data-test="runs-empty"]').text()).toContain('Nenhum problema')
  })

  it('sem execuções, mostra o vazio', async () => {
    const { w } = await mountTab({
      'GET /api/agents/1/runs?limit=50': () => jsonResponse([]),
      'GET /api/agents/2/runs?limit=50': () => jsonResponse([]),
    })
    expect(w.get('[data-test="runs-empty"]').text()).toContain('Ainda não rodou')
  })

  it('uma falha ao carregar um agente avisa e mantém os outros', async () => {
    const { w } = await mountTab({ 'GET /api/agents/2/runs?limit=50': () => jsonResponse({ detail: 'Quebrou ao ler.' }, 500) })
    expect(w.get('[data-test="runs-error"]').attributes('role')).toBe('alert')
    expect(w.get('[data-test="runs-error"]').text()).toContain('Quebrou ao ler.')
    expect(ids(w)).toEqual(['2', '1'])
  })

  it('uma execução nova que chega por evento entra na lista', async () => {
    const { w } = await mountTab()
    useOrgStore(pinia).applyEvent('agent.run', makeRun({ id: 9, agent_id: 1, started_at: t + 900, outcome: 'running' }))
    await flushPromises()
    expect(ids(w)[0]).toBe('9')
  })
})
