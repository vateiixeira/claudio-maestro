import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { ref } from 'vue'
import type { ConnectionStatus } from '../../../types/events'

const socketStatus = vi.hoisted(() => ({ current: null as unknown as { value: ConnectionStatus } }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({ status: socketStatus.current }),
}))

import AppSidebar from '../AppSidebar.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useGroupsStore } from '../../../stores/groups'
import { useNewConversationStore } from '../../../stores/newConversation'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { setCollapsed } from '../../../sidebarCollapse'
import { makeGitRepo, makeGroup, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  socketStatus.current = ref<ConnectionStatus>('connected')
})

function mountSidebar() {
  const router = createAppRouter(createMemoryHistory())
  return mount(AppSidebar, { global: { plugins: [pinia, router] } })
}

describe('menu lateral', () => {
  it('tem as entradas fixas', () => {
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="nav-dashboard"]').attributes('href')).toBe('/dashboard')
    expect(wrapper.find('[data-test="nav-inbox"]').attributes('href')).toBe('/inbox')
    expect(wrapper.find('[data-test="nav-conversations"]').attributes('href')).toBe('/sessions')
    expect(wrapper.find('[data-test="preferences"]').attributes('href')).toBe('/preferencias')
    expect(wrapper.find('[data-test="new-project"]').attributes('href')).toBe('/projects/new')
  })

  it('conta na Inbox as conversas que aguardam você', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'b', display_state: 'waiting', pending_kind: 'question' }),
      makeSession({ session_id: 'c', display_state: 'running' }),
      makeSession({ session_id: 'd', display_state: 'waiting', unread: false }),
    ])
    expect(mountSidebar().find('[data-test="inbox-count"]').text()).toBe('2')
  })

  it('não conta na Inbox nem no projeto a espera comum, sem novidade', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: false }),
    ])
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="inbox-count"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="project-waiting"]').exists()).toBe(false)
  })

  it('lista projetos com cor, branch e aguardando, sem conversas aninhadas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
    useSessionsStore(pinia).setForProject(1, [makeSession({ display_state: 'waiting', unread: true })])

    const project = mountSidebar().find('[data-test="project"]')
    expect(project.attributes('href')).toBe('/projects/1')
    expect(project.find('[data-test="project-name"]').text()).toBe('loja-online')
    expect(project.find('[data-test="project-branch"]').text()).toContain('develop')
    expect(project.find('[data-test="project-waiting"]').text()).toContain('1')
    expect(mountSidebar().find('[data-test="session"]').exists()).toBe(false)
  })

  const titles = (w: ReturnType<typeof mountSidebar>) =>
    w.findAll('[data-test="recent"]').map((r) => r.find('[data-test="row-title"]').text())

  it('Recentes lista todas as conversas não finalizadas pela última interação, sem depender de terem sido abertas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 }), makeProject({ id: 2 })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, title: 'A', last_activity_at: 100 }),
      makeSession({ session_id: 'c', project_id: 1, title: 'C', last_activity_at: 300 }),
    ])
    sessions.setForProject(2, [makeSession({ session_id: 'b', project_id: 2, title: 'B', last_activity_at: 200 })])

    const recent = mountSidebar().findAll('[data-test="recent"]')
    expect(recent.map((r) => r.find('[data-test="row-title"]').text())).toEqual(['C', 'B', 'A'])
    expect(recent[0]!.attributes('href')).toBe('/sessions/c')
  })

  it('Recentes não tem teto: mais de 5 conversas aparecem', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 8 }, (_, i) =>
      makeSession({ session_id: `s${i}`, title: `T${i}`, last_activity_at: 1000 + i }),
    ))
    expect(titles(mountSidebar())).toEqual(['T7', 'T6', 'T5', 'T4', 'T3', 'T2', 'T1', 'T0'])
  })

  it('marca com aria-current só o link da conversa aberta em Recentes', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', title: 'A', last_activity_at: 200 }),
      makeSession({ session_id: 's2', title: 'B', last_activity_at: 100 }),
    ])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s2')
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })

    const links = wrapper.findAll('[data-test="recent"]')
    expect(links.map((l) => l.attributes('aria-current'))).toEqual([undefined, 'page'])
  })

  it('Recentes não repete o que está em execução', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, display_state: 'running' }),
      makeSession({ session_id: 'b', project_id: 1 }),
    ])
    const w = mountSidebar()
    await flushPromises()
    expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toEqual(['/sessions/b'])
    expect(w.findAll('[data-test="running"]').length).toBe(1)
  })

  it('conversa que para de rodar passa de "Em execução" para Recentes', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [makeSession({ session_id: 'cli', project_id: 1, display_state: 'running', cli_running: true })])
    const w = mountSidebar()
    expect(w.find('[data-test="recent"]').exists()).toBe(false)
    sessions.find('cli')!.display_state = 'waiting'
    await flushPromises()
    expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toEqual(['/sessions/cli'])
    expect(w.find('[data-test="running"]').exists()).toBe(false)
  })

  it('linhas de Recentes mostram o nome do projeto depois do título, sem badge', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'b', project_id: 1 })])
    const w = mountSidebar()
    const row = w.find('[data-test="recent"]')
    expect(row.find('[data-test="row-project"]').text()).toBe('loja-online')
    expect(row.find('[data-test="row-project"]').attributes('title')).toBe('loja-online')
    expect(row.find('[data-test="project-badge"]').exists()).toBe(false)
  })

  it('Recentes não mostra conversa finalizada e ela volta ao ser reaberta', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, last_activity_at: 100 }),
      makeSession({ session_id: 'b', project_id: 1, last_activity_at: 200, display_state: 'finished', finished: true }),
    ])
    const w = mountSidebar()
    await flushPromises()
    expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toEqual(['/sessions/a'])
    sessions.find('b')!.display_state = 'waiting'
    await flushPromises()
    expect(w.findAll('[data-test="recent"]').map((r) => r.attributes('href'))).toEqual(['/sessions/b', '/sessions/a'])
  })

  it('conversa com nova interação sobe para o topo de Recentes', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, title: 'A', last_activity_at: 300 }),
      makeSession({ session_id: 'b', project_id: 1, title: 'B', last_activity_at: 200 }),
      makeSession({ session_id: 'c', project_id: 1, title: 'C', last_activity_at: 100 }),
    ])
    const w = mountSidebar()
    expect(titles(w)).toEqual(['A', 'B', 'C'])

    sessions.applyEvent({
      type: 'session.updated', session_id: 'c', seq: 1,
      data: makeSession({ session_id: 'c', project_id: 1, title: 'C', last_activity_at: 400 }),
    } as never)
    await flushPromises()
    expect(titles(w)).toEqual(['C', 'A', 'B'])
  })

  it('a barra lateral tem 308px de largura', () => {
    const w = mountSidebar()
    expect(w.find('nav').classes()).toContain('w-[308px]')
  })

  it('"Nova conversa" abre o modal', async () => {
    const wrapper = mountSidebar()
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
  })

  it('"Nova conversa" numa conversa abre o modal no agrupador dela', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', project_id: 1, group_id: 4 })])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    const store = useNewConversationStore(pinia)
    expect(store.presetProjectId).toBe(1)
    expect(store.presetGroupId).toBe(4)
  })

  it('"Nova conversa" numa conversa sem agrupador pede "Nenhum" (null)', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', project_id: 1, group_id: null })])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    expect(useNewConversationStore(pinia).presetGroupId).toBeNull()
  })

  it('"Nova conversa" fora de uma conversa não indica agrupador (undefined)', async () => {
    const wrapper = mountSidebar()
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    expect(useNewConversationStore(pinia).presetGroupId).toBeUndefined()
  })

  it('mostra o indicador de conexão no rodapé, abaixo de Preferências, só sem conexão', async () => {
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="connection-lost"]').exists()).toBe(false)

    socketStatus.current.value = 'reconnecting'
    await wrapper.vm.$nextTick()
    const lost = wrapper.find('[data-test="connection-lost"]')
    expect(lost.text()).toContain('Sem conexão com o servidor')
    const preferences = wrapper.find('[data-test="preferences"]').element
    expect(preferences.compareDocumentPosition(lost.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(wrapper.element.contains(lost.element)).toBe(true)
  })
})

describe('menu lateral em árvore', () => {
  beforeEach(() => { setCollapsed('project', 1, false) })

  it('não mostra a seta do projeto sem agrupadores', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    expect(mountSidebar().find('[data-test="project-toggle"]').exists()).toBe(false)
  })

  it('mostra os agrupadores do projeto e recolhe pela seta', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ group_id: 1, display_state: 'running' })])
    const wrapper = mountSidebar()
    const toggle = wrapper.find('[data-test="project-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.attributes('aria-label')).toBe('Recolher loja-online')
    expect(wrapper.find('[data-test="sidebar-group"]').exists()).toBe(true)
    await toggle.trigger('click')
    expect(wrapper.find('[data-test="sidebar-group"]').exists()).toBe(false)
    expect(toggle.attributes('aria-label')).toBe('Expandir loja-online')
  })

  it('o nome do projeto continua levando à tela do projeto', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1 })]
    const router = createAppRouter(createMemoryHistory())
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })
    await wrapper.find('[data-test="project"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/projects/1')
  })
})
