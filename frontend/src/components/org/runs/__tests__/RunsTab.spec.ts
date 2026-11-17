import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import RunsTab from '../RunsTab.vue'
import { createAppRouter } from '../../../../router'
import { clockNow } from '../../../../minuteClock'
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

const at = (day: number, hour: number, minute: number) => new Date(2026, 10, day, hour, minute).getTime() / 1000
const days = (w: ReturnType<typeof mount>) => w.findAll('[data-test="run-day"]').map((d) => d.attributes('data-day'))

describe('RunsTab', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 10, 17, 10, 40))
    clockNow.value = Date.now()
  })
  afterEach(() => vi.useRealTimers())

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

  it('agrupa por dia, do mais novo ao mais antigo', async () => {
    const mixed = [
      makeRun({ id: 1, agent_id: 1, started_at: at(13, 18, 40), ended_at: at(13, 18, 41), outcome: 'concluded' }),
      makeRun({ id: 2, agent_id: 1, started_at: at(17, 8, 0), ended_at: at(17, 8, 1), outcome: 'concluded' }),
    ]
    const { w } = await mountTab({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse(mixed), 'GET /api/agents/2/runs?limit=50': () => jsonResponse([]) })
    expect(days(w)).toEqual(['2026-11-17', '2026-11-13'])
    expect(w.findAll('[data-test="run-day-label"]').map((l) => l.text())).toEqual(['Hoje', '13 nov · sexta'])
    expect(w.findAll('[data-test="run-day"]')[1]!.findAll('[data-test="run-row"]')).toHaveLength(1)
  })

  it('perdidas do mesmo minuto viram uma linha', async () => {
    const t = at(10, 9, 4)
    const missed = [
      makeRun({ id: 1, agent_id: 1, started_at: t, ended_at: t, outcome: 'missed' }),
      makeRun({ id: 2, agent_id: 2, started_at: t + 10, ended_at: t + 10, outcome: 'missed' }),
    ]
    const { w } = await mountTab({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse([missed[0]]), 'GET /api/agents/2/runs?limit=50': () => jsonResponse([missed[1]]) })
    expect(w.findAll('[data-test="run-row"]')).toHaveLength(1)
    expect(w.get('[data-test="run-row"]').attributes('data-group-size')).toBe('2')
    expect(w.get('[data-test="run-headline"]').text()).toBe('2 perdidas: CTO e Dev')
  })

  it('o filtro Problemas mostra a contagem e esconde as concluídas', async () => {
    const mixed = [
      makeRun({ id: 1, agent_id: 1, started_at: at(16, 8, 0), ended_at: at(16, 8, 1), outcome: 'concluded' }),
      makeRun({ id: 2, agent_id: 1, started_at: at(16, 9, 0), ended_at: at(16, 9, 1), outcome: 'failed' }),
      makeRun({ id: 3, agent_id: 1, started_at: at(16, 10, 0), ended_at: at(16, 10, 0), outcome: 'missed' }),
      makeRun({ id: 4, agent_id: 1, started_at: at(16, 11, 0), ended_at: at(16, 11, 0), outcome: 'missed' }),
    ]
    const { w } = await mountTab({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse(mixed), 'GET /api/agents/2/runs?limit=50': () => jsonResponse([]) })
    const chip = w.get('[data-test="runs-filter-problems"]')
    expect(chip.get('[data-test="filter-chip-count"]').text()).toBe('3')
    expect(ids(w)).toEqual(['4', '3', '2', '1'])
    await chip.trigger('click')
    expect(chip.attributes('aria-pressed')).toBe('true')
    expect(ids(w)).toEqual(['4', '3', '2'])
  })

  it('avisa dos agentes desligados e some quando todos estão ligados', async () => {
    const { w } = await mountTab()
    expect(w.find('[data-test="runs-off"]').exists()).toBe(false)
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, slug: 'cto', name: 'CTO' }),
      makeAgent({ id: 2, slug: 'dev', name: 'Triagem', reports_to: 1, enabled: false }),
    ]
    await flushPromises()
    expect(w.get('[data-test="runs-off"]').text()).toBe('Triagem está desligado: nada dele roda até você ligar.')
  })

  it('traz o resumo das execuções carregadas', async () => {
    const { w } = await mountTab()
    expect(w.get('[data-test="runs-summary"]').text()).toMatch(/^.*: 2 concluídas, 1 com falha\.$/)
  })

  it('uma execução rodando, sem relato, convive com as outras', async () => {
    const { w } = await mountTab()
    expect(w.get('[data-run-id="4"] [data-test="run-headline"]').text()).toBe('Rodando')
    expect(w.find('[data-run-id="4"] [data-test="run-duration-bar"]').exists()).toBe(false)
  })

  it('uma perdida entra no dia e na hora agendados, mesmo percebida dias depois', async () => {
    const lost = (id: number, agent: number, scheduled: number) =>
      makeRun({ id, agent_id: agent, outcome: 'missed', scheduled_for: scheduled, started_at: at(16, 10, 15), ended_at: null })
    const { w } = await mountTab({
      'GET /api/agents/1/runs?limit=50': () => jsonResponse([
        lost(11, 1, at(13, 18, 40)),
        makeRun({ id: 12, agent_id: 1, outcome: 'concluded', started_at: at(16, 9, 0), ended_at: at(16, 9, 5) }),
      ]),
      'GET /api/agents/2/runs?limit=50': () => jsonResponse([lost(13, 2, at(13, 7, 40)), lost(14, 2, at(13, 8, 40))]),
    })
    expect(days(w)).toEqual(['2026-11-16', '2026-11-13'])
    // a concluída de segunda primeiro; sexta em ordem de hora agendada, 18:40 antes de 08:40 e 07:40; nada se juntou
    expect(ids(w)).toEqual(['12', '11', '14', '13'])
    expect(w.findAll('[data-test="run-started"]').map((e) => e.text())).toEqual(['09:00', '18:40', '08:40', '07:40'])
    expect(w.find('[data-group-size]').exists()).toBe(false)
  })

  it('Hoje e Ontem viram à meia-noite com o relógio do app', async () => {
    const { w } = await mountTab({
      'GET /api/agents/1/runs?limit=50': () => jsonResponse([makeRun({ id: 1, agent_id: 1, outcome: 'concluded', started_at: at(17, 9, 0), ended_at: at(17, 9, 5) })]),
      'GET /api/agents/2/runs?limit=50': () => jsonResponse([]),
    })
    const labels = () => w.findAll('[data-test="run-day-label"]').map((l) => l.text())
    expect(labels()).toEqual(['Hoje'])
    clockNow.value = new Date(2026, 10, 18, 0, 5).getTime()
    await flushPromises()
    expect(labels()).toEqual(['Ontem'])
    clockNow.value = Date.now()
  })

  it('sem a organização lida, não afirma que o projeto não tem agentes', async () => {
    useOrgStore(pinia).agents = []
    useOrgStore(pinia).loaded = false
    const { w } = await mountTab()
    expect(w.find('[data-test="runs-empty"]').exists()).toBe(false)
    useOrgStore(pinia).loaded = true
    await flushPromises()
    expect(w.get('[data-test="runs-empty"]').text()).toContain('ainda não tem agentes')
  })

  it('com erro ao ler os agentes, não afirma que o projeto não tem agentes', async () => {
    useOrgStore(pinia).agents = []
    useOrgStore(pinia).loaded = true
    useOrgStore(pinia).error = 'Falha ao ler os agentes.'
    const { w } = await mountTab()
    expect(w.find('[data-test="runs-empty"]').exists()).toBe(false)
  })

  it('enquanto os agentes não chegam, diz que está carregando', async () => {
    useOrgStore(pinia).agents = []
    useOrgStore(pinia).loaded = false
    const { w } = await mountTab()
    expect(w.get('[data-test="runs-loading"]').text()).toBe('Carregando execuções…')
  })
})
