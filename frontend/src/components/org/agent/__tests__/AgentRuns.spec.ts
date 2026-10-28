import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentRuns from '../AgentRuns.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeRun, routeFetch } from '../../../../test/factories'
import type { Wakeup } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
})
afterEach(() => vi.unstubAllGlobals())

const wakeup = (overrides: Partial<Wakeup> = {}): Wakeup => ({
  id: 7, agent_id: 1, source: 'message', priority: 0, routine_id: null, payload: null, state: 'pending',
  run_id: null, created_at: 1_790_000_000, taken_at: null, task_id: null, text: 'Revise o PR 12', ...overrides,
})

const RUNS = [
  makeRun({ id: 1, outcome: 'concluded', ended_at: 1_790_000_010, started_at: 1_790_000_000 }),
  makeRun({ id: 2, outcome: 'failed', reason: 'O processo caiu.', ended_at: 1_790_000_020, started_at: 1_790_000_015 }),
  makeRun({ id: 3, outcome: 'waiting', ended_at: null, started_at: 1_790_000_030 }),
  makeRun({ id: 4, outcome: 'missed', reason: 'O app estava fechado.', ended_at: 1_790_000_040, started_at: 1_790_000_040 }),
  makeRun({ id: 5, outcome: 'skipped', reason: 'Já havia uma execução.', ended_at: 1_790_000_050, started_at: 1_790_000_050 }),
  makeRun({ id: 6, outcome: 'cancelled', ended_at: 1_790_000_060, started_at: 1_790_000_060, task_id: 12, source: 'assignment' }),
]

async function mountRuns(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({
    'GET /api/agents/1/runs?limit=50': () => jsonResponse(RUNS),
    'GET /api/agents/1/wakeups': () => jsonResponse([]),
    ...handlers,
  })
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1?agente=1&aba=execucoes')
  await router.isReady()
  const wrapper = mount(AgentRuns, { props: { agentId: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, fetch }
}

const ids = (w: Awaited<ReturnType<typeof mountRuns>>['wrapper']) => w.findAll('[data-test="run-row"]').map((r) => r.attributes('data-run-id'))

describe('AgentRuns', () => {
  it('lista as execuções, a mais nova primeiro, e filtra problemas', async () => {
    const { wrapper } = await mountRuns()
    expect(ids(wrapper)).toEqual(['6', '5', '4', '3', '2', '1'])
    await wrapper.get('[data-test="run-filter-problems"]').trigger('click')
    expect(ids(wrapper)).toEqual(['5', '4', '3', '2'])
    expect(wrapper.get('[data-test="run-filter-problems"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[data-test="run-filter-all"]').trigger('click')
    expect(ids(wrapper)).toHaveLength(6)
  })

  it('filtro de problemas sem nenhum diz que não há problema', async () => {
    const { wrapper } = await mountRuns({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([RUNS[0]]) })
    await wrapper.get('[data-test="run-filter-problems"]').trigger('click')
    expect(wrapper.get('[data-test="runs-empty"]').text()).toBe('Nenhum problema no histórico.')
  })

  it('sem execuções diz que ainda não rodou', async () => {
    const { wrapper } = await mountRuns({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([]) })
    expect(wrapper.get('[data-test="runs-empty"]').text()).toBe('Ainda não rodou.')
  })

  it('linha com tarefa tem link', async () => {
    const { wrapper } = await mountRuns()
    const row = wrapper.get('[data-run-id="6"]')
    expect(row.get('[data-test="run-task"]').attributes('href')).toBe('/tarefas/12')
    expect(row.get('[data-test="run-source"]').text()).toBe('Tarefa')
  })

  it('mostra a fila de pedidos e cancela um', async () => {
    let queue = [wakeup()]
    const { wrapper, fetch } = await mountRuns({
      'GET /api/agents/1/wakeups': () => jsonResponse(queue),
      'POST /api/agents/1/wakeups/7/cancel': () => { queue = []; return jsonResponse({ id: 7, state: 'dropped' }) },
    })
    const row = wrapper.get('[data-test="wakeup-row"]')
    expect(row.text()).toContain('Mensagem')
    expect(row.text()).toContain('Revise o PR 12')
    await row.get('[data-test="wakeup-cancel"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/1/wakeups/7/cancel' && init?.method === 'POST')).toBe(true)
    expect(wrapper.find('[data-test="wakeup-row"]').exists()).toBe(false)
  })

  it('cancelar um pedido que já foi atendido mostra o erro e relê a fila', async () => {
    const { wrapper } = await mountRuns({
      'GET /api/agents/1/wakeups': () => jsonResponse([wakeup()]),
      'POST /api/agents/1/wakeups/7/cancel': () => jsonResponse({ detail: 'O pedido já foi atendido.' }, 409),
    })
    await wrapper.get('[data-test="wakeup-cancel"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="runs-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="runs-error"]').text()).toContain('O pedido já foi atendido.')
  })

  it('sem pedidos na fila não mostra a seção', async () => {
    const { wrapper } = await mountRuns()
    expect(wrapper.find('[data-test="wakeups"]').exists()).toBe(false)
  })

  it('uma mudança que não mexe na primeira execução não relê a fila', async () => {
    const { wrapper, fetch } = await mountRuns()
    const loads = () => fetch.mock.calls.filter(([u]) => u === '/api/agents/1/wakeups').length
    const before = loads()
    useOrgStore(pinia).applyEvent('agent.run', { ...RUNS[0]!, reason: 'texto novo' })
    await flushPromises()
    expect(ids(wrapper)).toHaveLength(6)
    expect(loads()).toBe(before)
  })

  it('uma execução que chega por evento entra na lista', async () => {
    const { wrapper } = await mountRuns()
    useOrgStore(pinia).applyEvent('agent.run', makeRun({ id: 9, outcome: 'running', started_at: 1_790_000_100 }))
    await flushPromises()
    expect(ids(wrapper)[0]).toBe('9')
  })
})
