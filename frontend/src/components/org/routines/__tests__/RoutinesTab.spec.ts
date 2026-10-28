import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import RoutinesTab from '../RoutinesTab.vue'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeRoutine, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
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
  const fetch = routeFetch({ 'GET /api/routines?project_id=1': () => jsonResponse(routines), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const w = mount(RoutinesTab, { props: { projectId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return { w, fetch }
}

describe('RoutinesTab', () => {
  it('mantém o data-test raiz e a prop da casca', async () => {
    const { w } = await mountTab()
    expect(w.attributes('data-test')).toBe('routines-tab')
    expect(w.attributes('data-project-id')).toBe('1')
  })

  it('lista com próximo disparo e marca cria tarefa', async () => {
    const { w } = await mountTab()
    const rows = w.findAll('[data-test="routine-row"]')
    expect(rows).toHaveLength(2)
    const first = rows[0]!
    expect(first.get('[data-test="routine-name-text"]').text()).toBe('Triagem da manhã')
    expect(first.get('[data-test="routine-agent-name"]').text()).toBe('CTO')
    expect(first.get('[data-test="routine-schedules"]').text()).toContain('seg–sex 08:00')
    expect(first.get('[data-test="routine-next"]').text()).toMatch(/^próximo: (seg|ter|qua|qui|sex) 08:00$/)
    expect(first.get('[data-test="routine-creates-task"]').text()).toBe('Cria tarefa')
    expect(first.get('[data-test="routine-state"]').text()).toBe('Ligada')
    const second = rows[1]!
    expect(second.find('[data-test="routine-creates-task"]').exists()).toBe(false)
    expect(second.get('[data-test="routine-state"]').text()).toBe('Desligada')
    expect(second.get('[data-test="routine-next"]').text()).toBe('rotina desligada')
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
    await w.findAll('[data-test="routine-delete"]')[0]!.trigger('click')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    await w.get('[data-test="routine-delete-confirm"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([url, init]) => url === '/api/routines/1' && init?.method === 'DELETE')).toBe(true)
    expect(w.findAll('[data-test="routine-row"]')).toHaveLength(1)
  })

  it('cancelar a exclusão não chama a API', async () => {
    const { w, fetch } = await mountTab()
    await w.findAll('[data-test="routine-delete"]')[0]!.trigger('click')
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
