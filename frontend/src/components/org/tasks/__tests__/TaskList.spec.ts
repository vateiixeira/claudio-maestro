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
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 2, name: 'Blog' }), makeProject({ id: 99, name: 'Sem projeto', path: '/home/vi/.local/share/claudio-maestro/scratch', kind: 'scratch', position: 99 })]
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
    expect(wrapper.get('[data-test="tasks-empty"]').text()).toContain('Nenhuma tarefa nos filtros selecionados.')
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

  it('o filtro de projeto não oferece o embutido "Sem projeto"', async () => {
    stubTasks(() => [])
    const { wrapper } = await mountList({ syncQuery: true }, '/tarefas')
    const options = wrapper.get('[data-test="project-filter"]').findAll('option').map((o) => o.text())
    expect(options).toContain('Loja')
    expect(options).toContain('Blog')
    expect(options).not.toContain('Sem projeto')
  })

  it('os quatro estados abertos são contadores ligados, e Concluída e Cancelada são chips desligados', async () => {
    stubTasks(() => [])
    const { wrapper } = await mountList()
    for (const status of ['todo', 'in_progress', 'in_review', 'blocked']) {
      const counter = wrapper.get(`[data-test="status-chip-${status}"]`)
      expect(counter.attributes('aria-pressed')).toBe('true')
      expect(counter.find('[data-test="status-count"]').exists()).toBe(true)
    }
    for (const status of ['done', 'cancelled']) {
      const chip = wrapper.get(`[data-test="status-chip-${status}"]`)
      expect(chip.attributes('aria-pressed')).toBe('false')
      expect(chip.find('[data-test="status-count"]').exists()).toBe(false)
    }
    await wrapper.get('[data-test="status-chip-todo"]').trigger('click')
    expect(wrapper.get('[data-test="status-chip-todo"]').attributes('aria-pressed')).toBe('false')
    await wrapper.get('[data-test="status-chip-cancelled"]').trigger('click')
    expect(wrapper.get('[data-test="status-chip-cancelled"]').attributes('aria-pressed')).toBe('true')
  })

  it('conta as tarefas abertas por estado, com os filtros de projeto e responsável', async () => {
    const urls = stubTasks((p) => {
      const all = [
        makeTask({ id: 1, status: 'todo', assignee_agent_id: 1 }),
        makeTask({ id: 2, status: 'todo', assignee_agent_id: 2 }),
        makeTask({ id: 3, status: 'in_progress', assignee_agent_id: 2 }),
        makeTask({ id: 4, status: 'done', assignee_agent_id: 2 }),
      ]
      const statuses = p.getAll('status')
      return all.filter((t) => (statuses.length === 0 || statuses.includes(t.status)) && (!p.get('assignee_agent_id') || String(t.assignee_agent_id) === p.get('assignee_agent_id')))
    })
    const { wrapper } = await mountList()
    expect(urls).toContain('/api/tasks?project_id=1&status=todo&status=in_progress&status=in_review&status=blocked&limit=500')
    const counts = () => ['todo', 'in_progress', 'in_review', 'blocked'].map((s) => wrapper.get(`[data-test="status-chip-${s}"] [data-test="status-count"]`).text())
    expect(counts()).toEqual(['2', '1', '0', '0'])
    expect(wrapper.find('[data-test="tasks-counts-truncated"]').exists()).toBe(false)

    await wrapper.get('[data-test="assignee-filter"]').setValue('2')
    await flushPromises()
    expect(urls).toContain('/api/tasks?project_id=1&status=todo&status=in_progress&status=in_review&status=blocked&assignee_agent_id=2&limit=500')
    expect(counts()).toEqual(['1', '1', '0', '0'])

    // The counts do not depend on which states are on.
    await wrapper.get('[data-test="status-chip-todo"]').trigger('click')
    await flushPromises()
    expect(counts()).toEqual(['1', '1', '0', '0'])
  })

  it('avisa quando a contagem passa do limite lido', async () => {
    stubTasks((p) => (p.get('limit') === '500' ? Array.from({ length: 500 }, (_, i) => makeTask({ id: i + 1 })) : []))
    const { wrapper } = await mountList()
    expect(wrapper.get('[data-test="tasks-counts-truncated"]').text()).toBe('Contagem das primeiras 500 tarefas abertas.')
  })

  it('vazio global com os filtros padrão explica a tarefa e mostra onde criar', async () => {
    useProjectsStore(pinia).projects = [
      makeProject({ id: 1, name: 'Loja Demo' }),
      makeProject({ id: 2, name: 'Blog Demo' }),
      makeProject({ id: 3, name: 'Docs Demo' }),
    ]
    useOrgStore(pinia).agents = [
      makeAgent({ id: 1, name: 'Maestro', project_id: 1 }),
      makeAgent({ id: 2, slug: 'revisor', name: 'Revisor', project_id: 1, reports_to: 1 }),
      makeAgent({ id: 3, slug: 'triagem', name: 'Triagem', project_id: 1, reports_to: 1 }),
    ]
    stubTasks(() => [])
    const openMain = vi.spyOn(useOrgStore(pinia), 'openMain').mockResolvedValue('s1')
    const { wrapper, router } = await mountList({ syncQuery: true }, '/tarefas')
    const empty = wrapper.get('[data-test="tasks-empty"]')
    expect(empty.get('h2').text()).toBe('Nenhuma tarefa aberta')
    expect(empty.text()).toContain('Uma tarefa é um pedido')
    expect(empty.text()).toContain('Onde criar')
    const rows = wrapper.findAll('[data-test="tasks-where-project"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.attributes('data-project-id')).toBe('1')
    expect(rows[0]!.get('[data-test="tasks-open-organization"]').text()).toBe('Loja Demo')
    expect(rows[0]!.get('[data-test="tasks-open-organization"]').attributes('href')).toBe('/projects/1?visao=organizacao')
    expect(rows[0]!.get('[data-test="tasks-where-agents"]').text()).toBe('Maestro, Revisor e Triagem')

    await rows[0]!.get('[data-test="tasks-where-new"]').trigger('click')
    expect(wrapper.emitted('new-task')).toEqual([[1]])

    await rows[0]!.get('[data-test="tasks-where-talk"]').trigger('click')
    await flushPromises()
    expect(openMain).toHaveBeenCalledWith(1, expect.anything())

    const others = wrapper.get('[data-test="tasks-where-others"]')
    expect(others.text()).toContain('Os outros 2 projetos ainda não têm organização.')
    const link = others.get('a')
    expect(link.text()).toBe('Criar uma organização')
    expect(link.attributes('href')).toBe('/agentes')
    void router
  })

  it('o aviso dos outros projetos fala no singular e some quando todos têm organização', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja Demo' }), makeProject({ id: 2, name: 'Blog Demo' })]
    useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'Maestro', project_id: 1 })]
    stubTasks(() => [])
    const { wrapper } = await mountList({ syncQuery: true }, '/tarefas')
    expect(wrapper.get('[data-test="tasks-where-others"]').text()).toContain('O outro projeto ainda não tem organização.')
    useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'Maestro', project_id: 1 }), makeAgent({ id: 2, slug: 'b', name: 'Blog', project_id: 2 })]
    await flushPromises()
    expect(wrapper.find('[data-test="tasks-where-others"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="tasks-where-project"]')).toHaveLength(2)
  })

  it('vazio com outros filtros usa a frase de sempre, sem o "Onde criar"', async () => {
    stubTasks(() => [])
    const { wrapper } = await mountList({ syncQuery: true }, '/tarefas?status=done')
    const empty = wrapper.get('[data-test="tasks-empty"]')
    expect(empty.text()).toContain('Nenhuma tarefa nos filtros selecionados.')
    expect(empty.text()).not.toContain('Nenhuma tarefa aberta')
    expect(wrapper.find('[data-test="tasks-where"]').exists()).toBe(false)
  })

  it('vazio dentro de um projeto orienta sem o "Onde criar"', async () => {
    stubTasks(() => [])
    const { wrapper } = await mountList()
    expect(wrapper.get('[data-test="tasks-empty"]').text()).toContain('Crie uma tarefa em Nova tarefa ou peça ao CTO.')
    expect(wrapper.find('[data-test="tasks-where"]').exists()).toBe(false)
  })

  it('sem projeto com organização o "Onde criar" não lista ninguém', async () => {
    useOrgStore(pinia).agents = []
    stubTasks(() => [])
    const { wrapper } = await mountList({ syncQuery: true }, '/tarefas')
    expect(wrapper.find('[data-test="tasks-where-project"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="tasks-where-others"]').text()).toContain('Nenhum projeto tem organização ainda.')
  })
})
