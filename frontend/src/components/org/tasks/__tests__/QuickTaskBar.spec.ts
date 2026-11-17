import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import QuickTaskBar from '../QuickTaskBar.vue'
import { createAppRouter } from '../../../../router'
import { useOrgStore } from '../../../../stores/org'
import { useProjectsStore } from '../../../../stores/projects'
import { useTasksStore } from '../../../../stores/tasks'
import { makeAgent, makeProject, makeTask } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).loaded = true
  useOrgStore(pinia).agents = [
    makeAgent({ id: 1, name: 'Maestro', project_id: 1 }),
    makeAgent({ id: 10, slug: 'chefe', name: 'Chefe', project_id: 2 }),
    makeAgent({ id: 11, slug: 'dev', name: 'Dev', project_id: 2, reports_to: 10 }),
  ]
  useProjectsStore(pinia).projects = [
    makeProject({ id: 1, name: 'Loja Demo' }),
    makeProject({ id: 2, name: 'Blog Demo' }),
    makeProject({ id: 3, name: 'Sem organização' }),
  ]
})
afterEach(() => vi.restoreAllMocks())

async function mountBar(props: { projectId: number | null } = { projectId: null }) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/tarefas')
  await router.isReady()
  const wrapper = mount(QuickTaskBar, { props, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

describe('QuickTaskBar', () => {
  it('lista só os projetos com agentes e começa no primeiro', async () => {
    const wrapper = await mountBar()
    const select = wrapper.get<HTMLSelectElement>('[data-test="quick-task-project"]')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['Blog Demo', 'Loja Demo'])
    expect(select.element.value).toBe('2')
  })

  it('começa no projeto recebido e avisa quando a pessoa troca', async () => {
    const wrapper = await mountBar({ projectId: 1 })
    expect(wrapper.get<HTMLSelectElement>('[data-test="quick-task-project"]').element.value).toBe('1')
    await wrapper.get('[data-test="quick-task-project"]').setValue('2')
    expect(wrapper.emitted('update:projectId')).toEqual([[2]])
  })

  it('o responsável vem com o agente do topo e deixa ficar sem ninguém', async () => {
    const wrapper = await mountBar({ projectId: 2 })
    const select = wrapper.get<HTMLSelectElement>('[data-test="quick-task-assignee"]')
    expect(select.element.value).toBe('10')
    expect(select.findAll('option').map((o) => o.text())).toEqual(['Sem responsável', 'Chefe', 'Dev'])
    await wrapper.get('[data-test="quick-task-project"]').setValue('1')
    expect(select.element.value).toBe('1')
  })

  it('Enter cria a tarefa, limpa o campo e mostra o link', async () => {
    const create = vi.spyOn(useTasksStore(pinia), 'create').mockResolvedValue(makeTask({ id: 42, project_id: 2, title: 'Separar chamados' }))
    const wrapper = await mountBar({ projectId: 2 })
    const title = wrapper.get<HTMLInputElement>('[data-test="quick-task-title"]')
    await title.setValue('  Separar chamados ')
    await title.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(create).toHaveBeenCalledWith({ project_id: 2, title: 'Separar chamados', assignee_agent_id: 10 })
    expect(title.element.value).toBe('')
    const created = wrapper.get('[data-test="quick-task-created"]')
    expect(created.text()).toContain('Tarefa #42 criada.')
    const link = created.get('a')
    expect(link.text()).toBe('Abrir')
    expect(link.attributes('href')).toBe('/tarefas/42')
    expect(document.activeElement).toBe(title.element)
  })

  it('o botão cria com o responsável escolhido, ou sem responsável', async () => {
    const create = vi.spyOn(useTasksStore(pinia), 'create').mockResolvedValue(makeTask({ id: 5 }))
    const wrapper = await mountBar({ projectId: 2 })
    await wrapper.get('[data-test="quick-task-assignee"]').setValue('')
    await wrapper.get('[data-test="quick-task-title"]').setValue('Sem dono')
    await wrapper.get('[data-test="quick-task-submit"]').trigger('click')
    await flushPromises()
    expect(create).toHaveBeenCalledWith({ project_id: 2, title: 'Sem dono', assignee_agent_id: null })
  })

  it('título vazio não cria', async () => {
    const create = vi.spyOn(useTasksStore(pinia), 'create')
    const wrapper = await mountBar({ projectId: 2 })
    await wrapper.get('[data-test="quick-task-title"]').setValue('   ')
    await wrapper.get('[data-test="quick-task-title"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(create).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="quick-task-submit"]').attributes('disabled')).toBeDefined()
  })

  it('falha mostra o erro e guarda o título', async () => {
    vi.spyOn(useTasksStore(pinia), 'create').mockRejectedValue(new Error('Banco indisponível.'))
    const wrapper = await mountBar({ projectId: 2 })
    const title = wrapper.get<HTMLInputElement>('[data-test="quick-task-title"]')
    await title.setValue('Algo')
    await title.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.get('[data-test="quick-task-error"]').text()).toContain('Banco indisponível.')
    expect(title.element.value).toBe('Algo')
    expect(wrapper.find('[data-test="quick-task-created"]').exists()).toBe(false)
  })

  it('o foco vai para o título', async () => {
    const wrapper = await mountBar({ projectId: 2 })
    ;(wrapper.vm as unknown as { focus: () => void }).focus()
    expect(document.activeElement).toBe(wrapper.get('[data-test="quick-task-title"]').element)
  })

  it('sem projeto com agentes não aparece', async () => {
    useOrgStore(pinia).agents = []
    const wrapper = await mountBar()
    expect(wrapper.find('[data-test="quick-task"]').exists()).toBe(false)
  })
})
