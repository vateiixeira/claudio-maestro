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

function mountSidebar() {
  const router = createAppRouter(createMemoryHistory())
  return mount(AppSidebar, { global: { plugins: [pinia, router] } })
}

describe('menu lateral', () => {
  it('mostra a marca, os projetos e o botão de novo projeto', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [
      makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' }),
      makeProject({ id: 2, name: 'blog-pessoal', color: '#4FD1C5', path: '/home/vi/blog' }),
    ]
    projects.loaded = true

    const wrapper = mountSidebar()

    expect(wrapper.text()).toContain('Vini7 Vibing')
    const items = wrapper.findAll('[data-test="project"]')
    expect(items.map((i) => i.find('[data-test="project-name"]').text())).toEqual(['loja-online', 'blog-pessoal'])
    expect(items[0]!.find('[data-test="project-color"]').attributes('style')).toContain('background-color: rgb(178, 140, 255)')
    expect(items[0]!.find('a').attributes('href')).toBe('/projects/1')

    const newProject = wrapper.find('[data-test="new-project"]')
    expect(newProject.text()).toContain('Novo projeto')
    expect(newProject.attributes('href')).toBe('/projects/new')
  })

  it('marca o projeto com pasta indisponível', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [
      makeProject({ id: 1, name: 'ok' }),
      makeProject({ id: 2, name: 'sumiu', available: false }),
    ]
    projects.loaded = true

    const wrapper = mountSidebar()
    const [ok, gone] = wrapper.findAll('[data-test="project"]')

    expect(ok!.attributes('data-available')).toBe('true')
    expect(ok!.text()).not.toContain('pasta indisponível')
    expect(gone!.attributes('data-available')).toBe('false')
    expect(gone!.text()).toContain('pasta indisponível')
  })

  it('lista as sessões de cada projeto com o indicador de estado', () => {
    const projects = useProjectsStore(pinia)
    projects.projects = [makeProject({ id: 1 })]
    projects.loaded = true
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'r', title: 'Rodando', state: 'running' }),
      makeSession({ session_id: 'c', title: 'Conectando', state: 'connecting' }),
      makeSession({ session_id: 'w', title: 'Esperando', state: 'awaiting_decision' }),
      makeSession({ session_id: 'e', title: 'Quebrou', state: 'error' }),
      makeSession({ session_id: 'i', title: 'Parada', state: 'idle' }),
      makeSession({ session_id: 'x', title: 'Fechada', state: 'closed' }),
    ])

    const wrapper = mountSidebar()
    const sessions = wrapper.findAll('[data-test="session"]')

    expect(sessions.map((s) => s.attributes('href'))).toEqual([
      '/sessions/r', '/sessions/c', '/sessions/w', '/sessions/e', '/sessions/i', '/sessions/x',
    ])
    const shapes = sessions.map((s) => s.find('[data-shape]').attributes('data-shape') ?? null)
    expect(shapes).toEqual(['circle', 'circle', 'triangle', 'triangle', 'none', 'none'])
    expect(sessions[0]!.text()).toContain('Rodando')
    expect(sessions[2]!.text()).toContain('Aguardando você')
  })

  it('convida a criar projeto quando não há nenhum', () => {
    const projects = useProjectsStore(pinia)
    projects.loaded = true
    const wrapper = mountSidebar()
    expect(wrapper.findAll('[data-test="project"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('Nenhum projeto ainda')
  })
})
