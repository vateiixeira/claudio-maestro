import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import TasksView from '../TasksView.vue'
import { createAppRouter } from '../../router'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeAgent, makeProject, makeTask } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
  useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'CTO' })]
  useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'Loja' }), makeProject({ id: 2, name: 'Blog' })]
})
afterEach(() => vi.unstubAllGlobals())

describe('TasksView', () => {
  it('filtro de projeto na query', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url)
      return jsonResponse([makeTask({ id: 3, project_id: 2, title: 'Post novo' })])
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/tarefas?projeto=2&status=todo,done')
    await router.isReady()
    const wrapper = mount(TasksView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(urls.at(-1)).toBe('/api/tasks?project_id=2&status=todo&status=done')
    expect(wrapper.get('h1').text()).toBe('Tarefas')
    expect(wrapper.get<HTMLSelectElement>('[data-test="project-filter"]').element.value).toBe('2')
    expect(wrapper.get('[data-test="status-chip-done"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="status-chip-in_progress"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-test="task-row"]').text()).toContain('Post novo')

    await wrapper.get('[data-test="project-filter"]').setValue('')
    await flushPromises()
    expect(router.currentRoute.value.query.projeto).toBeUndefined()
    expect(urls.at(-1)).toBe('/api/tasks?status=todo&status=done')
  })
})

it('mostra o subtítulo e a barra de tarefa rápida antes da lista', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeTask({ id: 3, title: 'Post novo' })])))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/tarefas')
  const w = mount(TasksView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(w.text()).toContain('O trabalho entregue às organizações de todos os projetos.')
  const bar = w.get('[data-test="quick-task"]').element
  const row = w.get('[data-test="task-row"]').element
  expect(bar.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('sem organização em nenhum projeto a barra não aparece', async () => {
  useOrgStore(pinia).agents = []
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/tarefas')
  const w = mount(TasksView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(w.find('[data-test="quick-task"]').exists()).toBe(false)
})

it('no estado vazio leva à organização do projeto', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/tarefas')
  const w = mount(TasksView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  expect(w.get('[data-test="tasks-empty"]').text()).toContain('Nenhuma tarefa aberta')
  expect(w.get('[data-test="tasks-open-organization"]').attributes('href')).toBe('/projects/1?visao=organizacao')
})

it('Nova tarefa do "Onde criar" escolhe o projeto na barra e foca o título', async () => {
  useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'CTO', project_id: 1 }), makeAgent({ id: 2, slug: 'b', name: 'Chefe do Blog', project_id: 2 })]
  const fetch = vi.fn(async () => jsonResponse([]))
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/tarefas')
  const w = mount(TasksView, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  expect(w.get<HTMLSelectElement>('[data-test="quick-task-project"]').element.value).toBe('2')
  await w.get('[data-project-id="1"] [data-test="tasks-where-new"]').trigger('click')
  await flushPromises()
  expect(w.get<HTMLSelectElement>('[data-test="quick-task-project"]').element.value).toBe('1')
  expect(w.get<HTMLSelectElement>('[data-test="quick-task-assignee"]').element.value).toBe('1')
  expect(document.activeElement).toBe(w.get('[data-test="quick-task-title"]').element)
})
