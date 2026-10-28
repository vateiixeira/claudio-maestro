import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import RoutineForm from '../RoutineForm.vue'
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
    makeAgent({ id: 3, slug: 'outro', name: 'De outro projeto', project_id: 2 }),
  ]
})

function mountForm(props: Record<string, unknown> = {}) {
  return mount(RoutineForm, { props: { projectId: 1, ...props }, global: { plugins: [pinia] } })
}

const bodyOf = (fetch: ReturnType<typeof routeFetch>, key: string) => {
  const call = fetch.mock.calls.find(([url, init]) => `${init?.method ?? 'GET'} ${url}` === key)
  return call ? JSON.parse(call[1]!.body as string) : undefined
}

describe('RoutineForm', () => {
  it('valida nome e instrução', async () => {
    const fetch = routeFetch({})
    vi.stubGlobal('fetch', fetch)
    const w = mountForm()
    await w.get('form').trigger('submit')
    expect(w.get('[data-test="routine-name-error"]').text()).toBe('O nome da rotina precisa ter de 1 a 80 caracteres.')
    expect(w.get('[data-test="routine-instruction-error"]').text()).toBe('A instrução da rotina precisa ter de 1 a 5000 caracteres.')
    expect(w.get('[data-test="routine-name-error"]').attributes('role')).toBe('alert')

    await w.get('[data-test="routine-name"]').setValue('x'.repeat(81))
    await w.get('[data-test="routine-instruction"]').setValue('y'.repeat(5001))
    expect(w.get('[data-test="routine-instruction-count"]').text()).toBe('5001 / 5000')
    await w.get('form').trigger('submit')
    expect(w.find('[data-test="routine-name-error"]').exists()).toBe(true)
    expect(w.find('[data-test="routine-instruction-error"]').exists()).toBe(true)

    await w.get('[data-test="routine-name"]').setValue('   ')
    await w.get('form').trigger('submit')
    expect(w.find('[data-test="routine-name-error"]').exists()).toBe(true)
    expect(fetch).not.toHaveBeenCalled()
    expect(w.emitted('saved')).toBeUndefined()
  })

  it('só oferece os agentes do projeto', () => {
    const w = mountForm()
    const options = w.get('[data-test="routine-agent"]').findAll('option').map((o) => o.text())
    expect(options).toEqual(['CTO', 'Dev'])
  })

  it('envia schedules e create_task', async () => {
    const created = makeRoutine({ id: 9 })
    const fetch = routeFetch({ 'POST /api/routines': () => jsonResponse(created, 201) })
    vi.stubGlobal('fetch', fetch)
    const w = mountForm()
    await w.get('[data-test="routine-name"]').setValue('  Triagem  ')
    await w.get('[data-test="routine-agent"]').setValue('2')
    await w.get('[data-test="routine-instruction"]').setValue('Veja os erros novos.')
    await w.get('[data-test="routine-create-task"]').setValue(true)
    await w.get('[data-test="schedule-add"]').trigger('click')
    await w.get('[data-test="schedule-time"]').setValue('08:00')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(bodyOf(fetch, 'POST /api/routines')).toEqual({
      project_id: 1,
      agent_id: 2,
      name: 'Triagem',
      instruction: 'Veja os erros novos.',
      enabled: true,
      create_task: true,
      schedules: [{ days: '12345', time: '08:00' }],
    })
    expect(w.emitted('saved')![0]).toEqual([created])
  })

  it('explica o que a opção de criar tarefa muda', () => {
    const w = mountForm()
    expect(w.text()).toContain('A tarefa fica no quadro, com histórico; sem isso a rotina roda numa sessão isolada')
  })

  it('exige dia e hora em cada horário', async () => {
    const fetch = routeFetch({})
    vi.stubGlobal('fetch', fetch)
    const w = mountForm()
    await w.get('[data-test="routine-name"]').setValue('Triagem')
    await w.get('[data-test="routine-instruction"]').setValue('Veja.')
    await w.get('[data-test="schedule-add"]').trigger('click')
    for (const index of [0, 1, 2, 3, 4]) await w.findAll('[data-test="day"]')[index]!.trigger('click')
    await w.get('form').trigger('submit')
    expect(w.get('[data-test="routine-schedules-error"]').text()).toBe('Escolha ao menos um dia em cada horário.')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('edita: preenche, não deixa trocar o agente e manda PATCH', async () => {
    const routine = makeRoutine({
      id: 5, agent_id: 2, name: 'Antiga', instruction: 'Texto', enabled: false, create_task: true,
      schedules: [{ id: 1, days: '135', time: '07:30', last_fired_at: null }],
    })
    const fetch = routeFetch({ 'PATCH /api/routines/5': () => jsonResponse({ ...routine, name: 'Nova' }) })
    vi.stubGlobal('fetch', fetch)
    const w = mountForm({ routine })
    expect((w.get('[data-test="routine-name"]').element as HTMLInputElement).value).toBe('Antiga')
    expect(w.get('[data-test="routine-agent"]').attributes('disabled')).toBeDefined()
    expect((w.get('[data-test="routine-agent"]').element as HTMLSelectElement).value).toBe('2')
    expect((w.get('[data-test="routine-enabled"]').element as HTMLInputElement).checked).toBe(false)
    expect((w.get('[data-test="routine-create-task"]').element as HTMLInputElement).checked).toBe(true)
    await w.get('[data-test="routine-name"]').setValue('Nova')
    await w.get('form').trigger('submit')
    await flushPromises()
    expect(bodyOf(fetch, 'PATCH /api/routines/5')).toEqual({
      name: 'Nova', instruction: 'Texto', enabled: false, create_task: true,
      schedules: [{ days: '135', time: '07:30' }],
    })
    expect(w.emitted('saved')).toHaveLength(1)
  })

  it('mostra o erro da API e mantém o que foi digitado', async () => {
    const fetch = routeFetch({
      'POST /api/routines': () => jsonResponse({ detail: 'O horário 08:00 está repetido nos mesmos dias.' }, 422),
    })
    vi.stubGlobal('fetch', fetch)
    const w = mountForm()
    await w.get('[data-test="routine-name"]').setValue('Triagem')
    await w.get('[data-test="routine-instruction"]').setValue('Veja.')
    await w.get('form').trigger('submit')
    await flushPromises()
    const alert = w.get('[data-test="routine-error"]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toBe('O horário 08:00 está repetido nos mesmos dias.')
    expect((w.get('[data-test="routine-name"]').element as HTMLInputElement).value).toBe('Triagem')
    expect(w.emitted('saved')).toBeUndefined()
  })

  it('cancelar emite cancel', async () => {
    const w = mountForm()
    await w.get('[data-test="routine-cancel"]').trigger('click')
    expect(w.emitted('cancel')).toHaveLength(1)
  })

  it('sem agentes no projeto, avisa e não deixa salvar', () => {
    useOrgStore(pinia).agents = []
    const w = mountForm()
    expect(w.text()).toContain('Crie um agente')
    expect(w.get('[data-test="routine-submit"]').attributes('disabled')).toBeDefined()
  })
})
