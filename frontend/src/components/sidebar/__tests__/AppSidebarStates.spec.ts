import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGitRepo, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

function mountSidebar() {
  return mount(AppSidebar, { global: { plugins: [pinia, createAppRouter(createMemoryHistory())] } })
}

describe('menu lateral com estados', () => {
  it('marca o projeto com pasta indisponível', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1, name: 'ok' }), makeProject({ id: 2, name: 'sumiu', available: false })]
    projects.loaded = true

    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'b', project_id: 2 })])

    const [ok, gone] = mountSidebar().findAll('[data-test="project"]')

    expect(ok!.attributes('data-available')).toBe('true')
    expect(ok!.text()).not.toContain('pasta indisponível')
    expect(gone!.attributes('data-available')).toBe('false')
    expect(gone!.text()).toContain('pasta indisponível')
  })

  it('mostra o erro ao carregar os projetos', () => {
    useProjectsStore(pinia).loadError = 'sem conexão'
    const wrapper = mountSidebar()
    expect(wrapper.find('[role="alert"]').text()).toContain('Não foi possível carregar os projetos')
    expect(wrapper.find('[role="alert"]').text()).toContain('sem conexão')
  })

  it('convida a criar projeto quando não há nenhum', () => {
    useProjectsStore(pinia).loaded = true
    const wrapper = mountSidebar()
    expect(wrapper.findAll('[data-test="project"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('Nenhum projeto ainda')
  })

  it('avisa com texto curto quando o projeto passa de 50 repositórios', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 }), makeProject({ id: 2, name: 'outro', path: '/home/vi/outro' })]
    projects.loaded = true
    useGitStore(pinia).set(1, [makeGitRepo()], true)
    useGitStore(pinia).set(2, [makeGitRepo({ path: '/home/vi/outro' })], false)
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'b', project_id: 2 })])
    const items = mountSidebar().findAll('[data-test="project"]')
    expect(items[0]!.find('[data-test="repo-limit"]').text()).toBe('Só os 50 primeiros repositórios')
    expect(items[1]!.find('[data-test="repo-limit"]').exists()).toBe(false)
  })

  it('não mostra contagem na Inbox quando nada aguarda', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ display_state: 'running' })])
    expect(mountSidebar().find('[data-test="inbox-count"]').exists()).toBe(false)
  })
})

describe('menu com eventos de sessão', () => {
  it('fim de turno atualiza a contagem da Inbox e do projeto', async () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 })]
    projects.loaded = true
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [makeSession({ session_id: 's', title: 'Tarefa', display_state: 'running', state: 'running' })])
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="inbox-count"]').exists()).toBe(false)

    sessions.applyEvent({
      session_id: 's', seq: 5, type: 'session.updated',
      data: makeSession({ session_id: 's', title: 'Tarefa', state: 'idle', display_state: 'waiting', unread: true, seq: 5 }),
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-test="inbox-count"]').text()).toBe('1')
    expect(wrapper.find('[data-test="project-waiting"]').text()).toContain('1')
  })
})
