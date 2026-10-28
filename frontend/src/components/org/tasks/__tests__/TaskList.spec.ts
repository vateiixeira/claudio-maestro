import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import TaskList from '../TaskList.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { useProjectsStore } from '../../../../stores/projects'
import { jsonResponse, makeAgent, makeProject, makeTask } from '../../../../test/factories'
import type { Task } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
  useOrgStore(pinia).agents = [
    makeAgent({ id: 1, name: 'CTO' }),
    makeAgent({ id: 2, slug: 'dev', name: 'Dev', reports_to: 1 }),
  ]
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 2, name: 'Blog' })]
})
afterEach(() => vi.unstubAllGlobals())

/** A fetch that answers `GET /api/tasks` from `answer(params)` and remembers every URL it saw. */
function stubTasks(answer: (params: URLSearchParams) => Task[]) {
  const urls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(url)
    const [path, search = ''] = url.split('?')
    if (path !== '/api/tasks') return jsonResponse({ detail: `Sem resposta falsa para ${url}` }, 599)
    return jsonResponse(answer(new URLSearchParams(search)))
  }))
  return urls
}

async function mountList(props: Record<string, unknown> = { projectId: 1 }, path = '/agentes/1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(TaskList, { props, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('TaskList', () => {
  it('filtra por status e responsável', async () => {
    const urls = stubTasks((p) => {
      const all = [
        makeTask({ id: 1, title: 'Aberta do CTO', assignee_agent_id: 1 }),
        makeTask({ id: 2, title: 'Aberta do Dev', assignee_agent_id: 2 }),
        makeTask({ id: 3, title: 'Feita do Dev', assignee_agent_id: 2, status: 'done' }),
      ]
      const statuses = p.getAll('status')
      return all.filter((t) => (statuses.length === 0 || statuses.includes(t.status)) && (!p.get('assignee_agent_id') || String(t.assignee_agent_id) === p.get('assignee_agent_id')))
    })
    const { wrapper } = await mountList()
    // By default the open ones.
    expect(urls.at(-1)).toBe('/api/tasks?project_id=1&status=todo&status=in_progress&status=in_review&status=blocked')
    expect(wrapper.findAll('[data-test="task-row"]').map((r) => r.attributes('data-task-id'))).toEqual(['1', '2'])

    await wrapper.get('[data-test="status-chip-done"]').trigger('click')
    await flushPromises()
    expect(urls.at(-1)).toContain('status=done')
    expect(wrapper.findAll('[data-test="task-row"]')).toHaveLength(3)
    expect(wrapper.get('[data-test="status-chip-done"]').attributes('aria-pressed')).toBe('true')

    await wrapper.get('[data-test="assignee-filter"]').setValue('2')
    await flushPromises()
    expect(urls.at(-1)).toContain('assignee_agent_id=2')
    expect(wrapper.findAll('[data-test="task-row"]').map((r) => r.attributes('data-task-id'))).toEqual(['2', '3'])
  })

  it('sem nenhum chip marcado lista todas as tarefas', async () => {
    const urls = stubTasks(() => [])
    const { wrapper } = await mountList()
    for (const id of ['todo', 'in_progress', 'in_review', 'blocked']) await wrapper.get(`[data-test="status-chip-${id}"]`).trigger('click')
    await flushPromises()
    expect(urls.at(-1)).toBe('/api/tasks?project_id=1')
  })

  it('vazio orienta', async () => {
    stubTasks(() => [])
    const { wrapper } = await mountList()
    expect(wrapper.get('[data-test="tasks-empty"]').text()).toBe('Nenhuma tarefa. Crie uma ou peça ao CTO.')
    expect(wrapper.find('[data-test="task-row"]').exists()).toBe(false)
  })

  it('a linha mostra número, título, estado, responsável, prioridade alta e quando mudou', async () => {
    stubTasks(() => [
      makeTask({ id: 7, title: 'Trocar o gateway', status: 'in_review', assignee_agent_id: 2, priority: 'urgent', updated_at: Math.floor(Date.now() / 1000) - 600 }),
      makeTask({ id: 8, title: 'Ajustar texto', priority: 'normal', assignee_agent_id: null }),
    ])
    const { wrapper } = await mountList()
    const [first, second] = wrapper.findAll('[data-test="task-row"]')
    expect(first!.element.tagName).toBe('A')
    expect(first!.attributes('href')).toBe('/tarefas/7')
    expect(first!.text()).toContain('#7')
    expect(first!.text()).toContain('Trocar o gateway')
    expect(first!.get('[data-test="task-status"]').text()).toBe('Em revisão')
    expect(first!.get('[data-test="task-status"]').attributes('data-shape')).toBe('triangle')
    expect(first!.get('[data-test="task-row-assignee"]').text()).toBe('Dev')
    expect(first!.get('[data-test="task-row-priority"]').text()).toBe('Urgente')
    expect(first!.get('[data-test="task-row-updated"]').text()).toBe('há 10 min')
    expect(second!.find('[data-test="task-row-priority"]').exists()).toBe(false)
    expect(second!.get('[data-test="task-row-assignee"]').text()).toBe('Sem responsável')
  })

  it('trocar de projeto zera o responsável escolhido', async () => {
    const urls = stubTasks(() => [])
    const { wrapper } = await mountList()
    await wrapper.get('[data-test="assignee-filter"]').setValue('2')
    await flushPromises()
    expect(urls.at(-1)).toContain('assignee_agent_id=2')
    await wrapper.setProps({ projectId: 2 })
    await flushPromises()
    expect(urls.at(-1)).toBe('/api/tasks?project_id=2&status=todo&status=in_progress&status=in_review&status=blocked')
    expect(wrapper.get<HTMLSelectElement>('[data-test="assignee-filter"]').element.value).toBe('')
  })

  it('falha ao carregar mostra o erro e deixa tentar de novo', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => (fail ? jsonResponse({ detail: 'Banco indisponível.' }, 500) : jsonResponse([makeTask({ id: 1 })]))))
    const { wrapper } = await mountList()
    expect(wrapper.get('[role="alert"]').text()).toContain('Banco indisponível.')
    fail = false
    await wrapper.get('[data-test="tasks-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="task-row"]')).toHaveLength(1)
  })

  it('sem projeto fixo oferece o filtro de projeto, grava na URL e mostra o projeto na linha', async () => {
    const urls = stubTasks((p) => [makeTask({ id: 1, project_id: Number(p.get('project_id') ?? 2), title: 'Uma' })])
    const { wrapper, router } = await mountList({ syncQuery: true }, '/tarefas')
    expect(urls.at(-1)).toBe('/api/tasks?status=todo&status=in_progress&status=in_review&status=blocked')
    expect(wrapper.get('[data-test="task-row-project"]').text()).toBe('Blog')
    await wrapper.get('[data-test="project-filter"]').setValue('1')
    await flushPromises()
    expect(router.currentRoute.value.query.projeto).toBe('1')
    expect(urls.at(-1)).toContain('project_id=1')
    await wrapper.get('[data-test="status-chip-done"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.status).toBe('todo,in_progress,in_review,blocked,done')
  })
})
