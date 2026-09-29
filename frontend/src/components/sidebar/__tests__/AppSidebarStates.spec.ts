import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('menu lateral com estados', () => {
  it('esconde finalizadas e conta rodando e aguardando', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 }), makeProject({ id: 2, name: 'blog' })]
    projects.loaded = true
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'r', title: 'Rodando', display_state: 'running', state: 'running' }),
      makeSession({ session_id: 'w', title: 'Esperando', display_state: 'waiting', awaiting_decision: true, unread: true }),
      makeSession({ session_id: 'f', title: 'Acabou', display_state: 'finished', finished: true }),
    ])
    sessions.setForProject(2, [makeSession({ session_id: 'r2', project_id: 2, display_state: 'running' })])

    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })

    const [first, second] = wrapper.findAll('[data-test="project"]')
    const titles = first!.findAll('[data-test="session"]').map((s) => s.text())
    expect(titles.join()).toContain('Rodando')
    expect(titles.join()).toContain('Esperando')
    expect(titles.join()).not.toContain('Acabou')
    expect(first!.find('[data-test="count-running"]').text()).toBe('1')
    expect(first!.find('[data-test="count-waiting"]').text()).toBe('1')
    expect(second!.find('[data-test="count-running"]').text()).toBe('1')
    expect(second!.find('[data-test="count-waiting"]').exists()).toBe(false)

    const allLink = wrapper.find('[data-test="all-sessions"]')
    expect(allLink.attributes('href')).toBe('/sessions')
    expect(allLink.find('[data-test="count-running"]').text()).toBe('2')
    expect(allLink.find('[data-test="count-waiting"]').text()).toBe('1')

    const waiting = first!.findAll('[data-test="session"]').find((s) => s.text().includes('Esperando'))!
    expect(waiting.attributes('data-unread')).toBe('true')
    expect(waiting.find('[data-shape]').attributes('data-shape')).toBe('triangle')
  })
})

describe('menu com session.state', () => {
  it('error vira triângulo e connecting vira círculo', async () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 })]
    projects.loaded = true
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'e', title: 'Quebrou', display_state: 'running', state: 'running' }),
      makeSession({ session_id: 'c', title: 'Conectando', display_state: 'waiting' }),
    ])
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
    sessions.applyEvent({ session_id: 'e', seq: 1, type: 'session.state', data: { state: 'error', error: 'x' } })
    sessions.applyEvent({ session_id: 'c', seq: 1, type: 'session.state', data: { state: 'connecting', error: null } })
    await wrapper.vm.$nextTick()
    const [e, c] = wrapper.findAll('[data-test="session"]')
    expect(e!.find('[data-shape]').attributes('data-shape')).toBe('triangle')
    expect(e!.text()).toContain('Aguardando você')
    expect(c!.find('[data-shape]').attributes('data-shape')).toBe('circle')
    expect(c!.text()).toContain('Em execução')
  })
})

describe('menu com session.updated', () => {
  it('fim de turno marca novidade', async () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 })]
    projects.loaded = true
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [makeSession({ session_id: 's', title: 'Tarefa', display_state: 'running', state: 'running' })])
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
    sessions.applyEvent({
      session_id: 's', seq: 5, type: 'session.updated',
      data: makeSession({ session_id: 's', title: 'Tarefa', state: 'idle', display_state: 'waiting', unread: true, seq: 5 }),
    })
    await wrapper.vm.$nextTick()
    const row = wrapper.find('[data-test="session"]')
    expect(sessions.find('s')!.unread).toBe(true)
    expect(row.attributes('data-unread')).toBe('true')
    expect(row.text()).toContain('com novidade')
  })
})
