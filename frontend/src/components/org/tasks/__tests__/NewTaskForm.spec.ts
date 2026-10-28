import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NewTaskForm from '../NewTaskForm.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeTask, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const org = useOrgStore(pinia)
  org.loaded = true
  org.agents = [
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 }),
    makeAgent({ id: 1, name: 'CTO' }),
    makeAgent({ id: 9, slug: 'outro', name: 'De outro projeto', project_id: 2 }),
  ]
})
afterEach(() => vi.unstubAllGlobals())

async function mountForm() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/agentes/1')
  await router.isReady()
  const wrapper = mount(NewTaskForm, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('NewTaskForm', () => {
  it('responsável padrão é o topo', async () => {
    const { wrapper } = await mountForm()
    const assignee = wrapper.get<HTMLSelectElement>('[data-test="new-task-assignee"]')
    expect(assignee.element.value).toBe('1')
    expect([...assignee.element.options].map((o) => o.text)).toEqual(['Sem responsável', 'CTO', 'Dev'])
    expect(wrapper.get<HTMLSelectElement>('[data-test="new-task-reviewer"]').element.value).toBe('')
    expect(wrapper.get<HTMLSelectElement>('[data-test="new-task-priority"]').element.value).toBe('normal')
  })

  it('não envia sem título', async () => {
    const { wrapper } = await mountForm()
    expect(wrapper.get('[data-test="new-task-submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="new-task-title"]').setValue('  ')
    expect(wrapper.get('[data-test="new-task-submit"]').attributes('disabled')).toBeDefined()
  })

  it('cria e navega', async () => {
    const fetch = routeFetch({
      'POST /api/tasks': () => jsonResponse(makeTask({ id: 42, title: 'Revisar o frete' }), 201),
    })
    vi.stubGlobal('fetch', fetch)
    const { wrapper, router } = await mountForm()
    await wrapper.get('[data-test="new-task-title"]').setValue('Revisar o frete')
    await wrapper.get('[data-test="new-task-description"]').setValue('Ver o cálculo.')
    await wrapper.get('[data-test="new-task-assignee"]').setValue('2')
    await wrapper.get('[data-test="new-task-reviewer"]').setValue('1')
    await wrapper.get('[data-test="new-task-priority"]').setValue('high')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const call = fetch.mock.calls.find((c) => c[0] === '/api/tasks')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      project_id: 1,
      title: 'Revisar o frete',
      description: 'Ver o cálculo.',
      assignee_agent_id: 2,
      reviewer_agent_id: 1,
      priority: 'high',
    })
    expect(router.currentRoute.value.fullPath).toBe('/tarefas/42')
    expect(wrapper.emitted('created')).toHaveLength(1)
  })

  it('envio duplo cria uma tarefa só', async () => {
    let done!: (r: Response) => void
    const fetch = vi.fn(() => new Promise<Response>((resolve) => { done = resolve }))
    vi.stubGlobal('fetch', fetch)
    const { wrapper } = await mountForm()
    await wrapper.get('[data-test="new-task-title"]').setValue('Uma só')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    expect(fetch).toHaveBeenCalledTimes(1)
    done(jsonResponse(makeTask({ id: 5 }), 201))
    await flushPromises()
  })

  it('erro do servidor aparece e mantém o que foi digitado', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/tasks': () => jsonResponse({ detail: 'O título é grande demais.' }, 422) }))
    const { wrapper, router } = await mountForm()
    await wrapper.get('[data-test="new-task-title"]').setValue('Título')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('O título é grande demais.')
    expect(wrapper.get<HTMLInputElement>('[data-test="new-task-title"]').element.value).toBe('Título')
    expect(router.currentRoute.value.fullPath).toBe('/agentes/1')
  })

  it('cancelar avisa quem abriu', async () => {
    const { wrapper } = await mountForm()
    await wrapper.get('[data-test="new-task-cancel"]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
