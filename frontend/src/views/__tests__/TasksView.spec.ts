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
