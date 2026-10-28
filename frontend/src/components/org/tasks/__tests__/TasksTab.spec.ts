import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import TasksTab from '../TasksTab.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeTask } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
  useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'CTO' })]
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([makeTask({ id: 1 })])))
})
afterEach(() => vi.unstubAllGlobals())

describe('TasksTab', () => {
  it('abre e fecha o formulário de nova tarefa', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/agentes/1')
    await router.isReady()
    const wrapper = mount(TasksTab, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.attributes('data-test')).toBe('tasks-tab')
    expect(wrapper.attributes('data-project-id')).toBe('1')
    expect(wrapper.findAll('[data-test="task-row"]')).toHaveLength(1)
    expect(wrapper.find('form').exists()).toBe(false)
    await wrapper.get('[data-test="new-task"]').trigger('click')
    expect(wrapper.find('[data-test="new-task-title"]').exists()).toBe(true)
    await wrapper.get('[data-test="new-task-cancel"]').trigger('click')
    expect(wrapper.find('[data-test="new-task-title"]').exists()).toBe(false)
  })
})
