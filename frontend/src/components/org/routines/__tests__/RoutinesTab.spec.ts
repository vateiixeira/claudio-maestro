import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import RoutinesTab from '../RoutinesTab.vue'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeRoutine, makeRun, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => { vi.useRealTimers() })
let pinia: Pinia

// Tuesday, 10:40: the clock of the "next" labels.
const NOW = new Date(2026, 10, 17, 10, 40)

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: NOW })
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [
    makeAgent({ id: 1, slug: 'cto', name: 'CTO' }),
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 }),
  ]
})

const triage = makeRoutine({
  id: 1, agent_id: 1, name: 'Triagem da manhã', create_task: true,
  schedules: [{ id: 1, days: '12345', time: '08:00', last_fired_at: null }],
})
const weekly = makeRoutine({
  id: 2, agent_id: 2, name: 'Faxina semanal', enabled: false,
  schedules: [{ id: 2, days: '7', time: '20:00', last_fired_at: null }],
})

async function mountTab(handlers: Parameters<typeof routeFetch>[0] = {}, routines = [triage, weekly]) {
  const fetch = routeFetch({
    'GET /api/routines?project_id=1': () => jsonResponse(routines),
    'GET /api/agents/1/runs?limit=50': () => jsonResponse([]),
    'GET /api/agents/2/runs?limit=50': () => jsonResponse([]),
    ...handlers,
  })
  vi.stubGlobal('fetch', fetch)
  const w = mount(RoutinesTab, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return { w, fetch }
}

/** Opens the "more" menu of the row and picks Excluir. */
async function askDelete(w: ReturnType<typeof mount>, index: number): Promise<void> {
  await w.findAll('[data-test="routine-more"]')[index]!.trigger('click')
  document.body.querySelector<HTMLElement>('[data-test="more-menu-item"][data-id="delete"]')!.click()
  await flushPromises()
}

describe('RoutinesTab', () => {
  it('mantém o data-test raiz e a prop da casca', async () => {
    const { w } = await mountTab()
    expect(w.attributes('data-test')).toBe('routines-tab')
    expect(w.attributes('data-project-id')).toBe('1')
  })

  it('lista com agenda em frase, próxima e marca de cria tarefa', async () => {
    const { w } = await mountTab()
    const rows = w.findAll('[data-test="routine-row"]')
    expect(rows).toHaveLength(2)
    const first = rows[0]!
    expect(first.get('[data-test="routine-name-text"]').text()).toBe('Triagem da manhã')
    expect(first.get('[data-test="routine-agent-name"]').text()).toBe('agente CTO')
    expect(first.get('[data-test="routine-schedules"]').text()).toBe('De segunda a sexta às 08:00')
    expect(first.get('[data-test="routine-next"]').text()).toBe('amanhã 08:00')
    expect(first.get('[data-test="routine-creates-task"]').text()).toBe('Cria tarefa')
    expect(first.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('true')
    const second = rows[1]!
    expect(second.find('[data-test="routine-creates-task"]').exists()).toBe(false)
    expect(second.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('false')
    expect(second.get('[data-test="routine-blocked"]').text()).toBe('não roda: rotina desligada')
  })

  it('carrega as execuções dos agentes das rotinas uma vez cada', async () => {
    const { fetch } = await mountTab()
    const calls = (path: string) => fetch.mock.calls.filter(([url]) => url === path).length
    expect(calls('/api/agents/1/runs?limit=50')).toBe(1)
    expect(calls('/api/agents/2/runs?limit=50')).toBe(1)
  })

  it('mostra a última execução e o histórico da rotina', async () => {
    const at = Math.floor(new Date(2026, 10, 13, 18, 40).getTime() / 1000)
    const { w } = await mountTab({
      'GET /api/agents/1/runs?limit=50': () => jsonResponse([
        makeRun({ id: 9, agent_id: 1, routine_id: 1, outcome: 'concluded', started_at: at, ended_at: at + 1481 }),
        makeRun({ id: 8, agent_id: 1, routine_id: null, outcome: 'failed', started_at: at + 100, ended_at: at + 200 }),
      ]),
    })
    const first = w.findAll('[data-test="routine-row"]')[0]!
    expect(first.get('[data-test="routine-last"]').text()).toContain('13 nov 18:40')
    expect(first.get('[data-test="routine-last"]').text()).toContain('24 min 41 s')
    expect(first.findAll('[data-test="run-history-bar"]')).toHaveLength(1)
    expect(w.findAll('[data-test="routine-row"]')[1]!.get('[data-test="routine-last"]').text()).toContain('ainda não rodou')
  })

  it('falha ao ler as execuções não derruba a lista', async () => {
    const { w } = await mountTab({ 'GET /api/agents/1/runs?limit=50': () => jsonResponse({ detail: 'x' }, 500) })
    expect(w.find('[data-test="routines-error"]').exists()).toBe(false)
    expect(w.findAll('[data-test="routine-row"]')).toHaveLength(2)
  })

  it('o agente desligado bloqueia a rotina ligada', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, slug: 'cto', name: 'CTO', enabled: false }), makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 })]
    const { w } = await mountTab()
    const first = w.findAll('[data-test="routine-row"]')[0]!
    expect(first.get('[data-test="routine-blocked"]').text()).toBe('não roda: agente desligado')
  })

  it('rotina de agente removido aparece sem quebrar', async () => {
    const orphan = makeRoutine({ id: 3, agent_id: 99, name: 'Órfã', schedules: [{ id: 3, days: '1', time: '09:00', last_fired_at: null }] })
    const { w } = await mountTab({}, [orphan])
    expect(w.get('[data-test="routine-agent-name"]').text()).toBe('Agente removido')
  })

  it('a chave desliga a rotina e relê a lista', async () => {
    const listed = [{ ...triage }, weekly]
    const { w, fetch } = await mountTab({
      'PATCH /api/routines/1': () => { listed[0] = { ...triage, enabled: false }; return jsonResponse(listed[0]) },
      'GET /api/routines?project_id=1': () => jsonResponse(listed),
    })
    await w.get('[data-test="routine-toggle"]').trigger('click')
    await flushPromises()
    const patch = fetch.mock.calls.find(([url, init]) => url === '/api/routines/1' && init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ enabled: false })
    expect(w.findAll('[data-test="routine-toggle"]')[0]!.attributes('aria-checked')).toBe('false')
    expect(w.find('[data-test="routine-row-error"]').exists()).toBe(false)
  })

  it('a chave que falha ao salvar volta ao estado anterior e mostra o erro', async () => {
    const { w } = await mountTab({ 'PATCH /api/routines/1': () => jsonResponse({ detail: 'Não deu para salvar.' }, 500) })
    await w.get('[data-test="routine-toggle"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('true')
    expect(w.get('[data-test="routine-row-error"]').text()).toBe('Não deu para salvar.')
  })

  it('a chave mostra o novo estado enquanto salva', async () => {
    let release!: (r: Response) => void
    const pending = new Promise<Response>((resolve) => { release = resolve })
    const { w } = await mountTab({ 'PATCH /api/routines/1': () => pending as unknown as Response })
    await w.get('[data-test="routine-toggle"]').trigger('click')
    expect(w.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('false')
    expect(w.get('[data-test="routine-toggle"]').attributes('disabled')).toBeDefined()
    release(jsonResponse({ detail: 'Falhou.' }, 500))
    await flushPromises()
    expect(w.get('[data-test="routine-toggle"]').attributes('aria-checked')).toBe('true')
  })

  it('mostra os dias da semana, com hoje marcado', async () => {
    const { w } = await mountTab()
    const days = w.get('[data-test="routines-weekdays"]').findAll('[data-day]')
    expect(days.map((d) => d.text())).toEqual(['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'])
    expect(days.filter((d) => d.attributes('data-today') !== undefined).map((d) => d.text())).toEqual(['ter'])
  })

  it('a semana e o cabeçalho só aparecem de lg para cima', async () => {
    const { w } = await mountTab()
    expect(w.get('[data-test="routines-weekdays"]').classes()).toContain('lg:grid')
    expect(w.get('[data-test="routines-weekdays"]').classes()).toContain('hidden')
    expect(w.get('[data-test="routine-week"]').classes()).toContain('lg:grid')
    expect(w.get('[data-test="routine-week"]').classes()).toContain('hidden')
  })

  describe('aviso de agentes desligados', () => {
    const rt = (id: number, agent_id: number, enabled = true) =>
      makeRoutine({ id, agent_id, enabled, name: `R${id}`, schedules: [{ id, days: '1', time: '09:00', last_fired_at: null }] })
    const off = (...ids: number[]) => {
      useOrgStore(pinia).agents = [1, 2, 3].map((id) => makeAgent({ id, slug: `a${id}`, name: `A${id}`, enabled: !ids.includes(id) }))
    }
    async function notice(routines: ReturnType<typeof rt>[], offIds: number[]) {
      off(...offIds)
      const { w } = await mountTab({ 'GET /api/agents/3/runs?limit=50': () => jsonResponse([]) }, routines)
      return w.find('[data-test="routines-notice"]')
    }

    it('todas as ligadas de agentes desligados (plural)', async () => {
      const n = await notice([rt(1, 1), rt(2, 2)], [1, 2])
      expect(n.text()).toBe('2 rotinas ligadas, mas os agentes delas estão desligados: nada roda até ligar.')
    })
    it('uma só (singular)', async () => {
      const n = await notice([rt(1, 1)], [1])
      expect(n.text()).toBe('1 rotina ligada, mas o agente dela está desligado: nada roda até ligar.')
    })
    it('uma de três', async () => {
      const n = await notice([rt(1, 1), rt(2, 2), rt(3, 3)], [1])
      expect(n.text()).toBe('1 das 3 rotinas ligadas tem o agente desligado e não roda até ligar.')
    })
    it('duas de três', async () => {
      const n = await notice([rt(1, 1), rt(2, 2), rt(3, 3)], [1, 2])
      expect(n.text()).toBe('2 das 3 rotinas ligadas têm o agente desligado e não rodam até ligar.')
    })
    it('nenhuma: sem aviso', async () => {
      expect((await notice([rt(1, 1), rt(2, 2)], [])).exists()).toBe(false)
    })
    it('rotina desligada não entra na conta', async () => {
      expect((await notice([rt(1, 1, false), rt(2, 2)], [1])).exists()).toBe(false)
    })
  })

  it('sem rotinas, mostra o vazio e o botão', async () => {
    const { w } = await mountTab({}, [])
    expect(w.find('[data-test="routine-row"]').exists()).toBe(false)
    expect(w.get('[data-test="routines-empty"]').text()).toContain('Nenhuma rotina')
    expect(w.find('[data-test="routine-new"]').exists()).toBe(true)
  })

  it('mostra o erro de carregamento', async () => {
    const { w } = await mountTab({ 'GET /api/routines?project_id=1': () => jsonResponse({ detail: 'Falhou ao ler.' }, 500) })
    expect(w.get('[data-test="routines-error"]').attributes('role')).toBe('alert')
    expect(w.get('[data-test="routines-error"]').text()).toContain('Falhou ao ler.')
  })

  it('rodar agora chama a API', async () => {
    const { w, fetch } = await mountTab({
      'POST /api/routines/1/run': () => jsonResponse({ id: 7, title: 'Triagem da manhã', status: 'todo' }, 202),
    })
    await w.findAll('[data-test="routine-run"]')[0]!.trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([url, init]) => url === '/api/routines/1/run' && init?.method === 'POST')).toBe(true)
    expect(w.get('[data-test="routine-feedback"]').text()).toBe('Tarefa #7 criada.')
  })

  it('rodar agora sem tarefa avisa que disparou', async () => {
    const { w } = await mountTab({
      'POST /api/routines/2/run': () => jsonResponse({ id: 3, agent_id: 2, source: 'manual' }, 202),
    })
    await w.findAll('[data-test="routine-run"]')[1]!.trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="routine-feedback"]')[0]!.text()).toBe('Rotina disparada.')
  })

  it('rodar agora com agente desligado mostra o erro da API', async () => {
    const { w } = await mountTab({
      'POST /api/routines/1/run': () => jsonResponse({ detail: 'O agente está desligado.' }, 409),
    })
    await w.findAll('[data-test="routine-run"]')[0]!.trigger('click')
    await flushPromises()
    const alert = w.get('[data-test="routine-row-error"]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toBe('O agente está desligado.')
  })

  it('excluir pede confirmação e depois chama a API', async () => {
    const listed = [triage, weekly]
    const { w, fetch } = await mountTab({
      'DELETE /api/routines/1': () => { listed.splice(0, 1); return jsonResponse(undefined, 204) },
      'GET /api/routines?project_id=1': () => jsonResponse(listed),
    })
    await askDelete(w, 0)
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    await w.get('[data-test="routine-delete-confirm"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([url, init]) => url === '/api/routines/1' && init?.method === 'DELETE')).toBe(true)
    expect(w.findAll('[data-test="routine-row"]')).toHaveLength(1)
  })

  it('cancelar a exclusão não chama a API', async () => {
    const { w, fetch } = await mountTab()
    await askDelete(w, 0)
    await w.get('[data-test="routine-delete-cancel"]').trigger('click')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    expect(w.find('[data-test="routine-delete-confirm"]').exists()).toBe(false)
  })

  it('nova rotina abre o formulário e, ao salvar, recarrega a lista', async () => {
    const listed = [triage]
    const { w, fetch } = await mountTab({
      'GET /api/routines?project_id=1': () => jsonResponse(listed),
      'POST /api/routines': () => { listed.push(weekly); return jsonResponse(weekly, 201) },
    })
    await w.get('[data-test="routine-new"]').trigger('click')
    expect(w.find('[data-test="routine-form"]').exists()).toBe(true)
    await w.get('[data-test="routine-name"]').setValue('Faxina semanal')
    await w.get('[data-test="routine-instruction"]').setValue('Limpe.')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(fetch.mock.calls.some(([url, init]) => url === '/api/routines' && init?.method === 'POST')).toBe(true)
    expect(w.find('[data-test="routine-form"]').exists()).toBe(false)
    expect(w.findAll('[data-test="routine-row"]')).toHaveLength(2)
  })

  it('editar abre o formulário preenchido e cancelar o fecha', async () => {
    const { w } = await mountTab()
    await w.findAll('[data-test="routine-edit"]')[1]!.trigger('click')
    expect((w.get('[data-test="routine-name"]').element as HTMLInputElement).value).toBe('Faxina semanal')
    await w.get('[data-test="routine-cancel"]').trigger('click')
    expect(w.find('[data-test="routine-form"]').exists()).toBe(false)
  })

  it('o retorno de rodar agora some ao abrir o formulário', async () => {
    const { w } = await mountTab({
      'POST /api/routines/1/run': () => jsonResponse({ id: 3, agent_id: 1, source: 'manual' }, 202),
    })
    await w.findAll('[data-test="routine-run"]')[0]!.trigger('click')
    await flushPromises()
    expect(w.find('[data-test="routine-feedback"]').exists()).toBe(true)
    await w.get('[data-test="routine-new"]').trigger('click')
    expect(w.find('[data-test="routine-feedback"]').exists()).toBe(false)
  })

  it('a resposta atrasada do projeto anterior não mexe no estado do novo', async () => {
    let rejectOld!: (r: Response) => void
    const slow = new Promise<Response>((resolve) => { rejectOld = resolve })
    const fetch = routeFetch({
      'GET /api/routines?project_id=1': () => slow as unknown as Response,
      'GET /api/routines?project_id=2': () => jsonResponse([]),
    })
    vi.stubGlobal('fetch', fetch)
    const w = mount(RoutinesTab, { props: { projectId: 1 }, global: { plugins: [pinia] } })
    await flushPromises()
    await w.setProps({ projectId: 2 })
    await flushPromises()
    expect(w.find('[data-test="routines-empty"]').exists()).toBe(true)
    rejectOld(jsonResponse({ detail: 'Falhou ao ler.' }, 500))
    await flushPromises()
    expect(w.find('[data-test="routines-error"]').exists()).toBe(false)
    expect(w.find('[data-test="routines-empty"]').exists()).toBe(true)
  })
})
