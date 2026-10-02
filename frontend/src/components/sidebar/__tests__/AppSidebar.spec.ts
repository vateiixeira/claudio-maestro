import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { nextTick, ref } from 'vue'
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
import { sidebarWidth } from '../../../sidebarWidthPref'
import { makeGitRepo, makeGroup, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:sidebar-width')
  sidebarWidth.value = 288
  socketStatus.current = ref<ConnectionStatus>('connected')
})

// jsdom has no PointerEvent, so trigger() cannot set clientX: dispatch a MouseEvent with the pointer event name.
async function pointer(handle: { element: Element }, type: string, clientX: number) {
  handle.element.dispatchEvent(new MouseEvent(type, { clientX, bubbles: true, cancelable: true }))
  await nextTick()
}

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
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="inbox-count"]').text()).toBe('2')
    expect(wrapper.find('[data-test="nav-inbox"] .sr-only').text()).toContain('aguardando você')
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

  it('lista projetos com cor, branch e aguardando', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
    useSessionsStore(pinia).setForProject(1, [makeSession({ display_state: 'waiting', unread: true })])

    const project = mountSidebar().find('[data-test="project"]')
    expect(project.attributes('href')).toBe('/projects/1')
    expect(project.find('[data-test="project-name"]').text()).toBe('loja-online')
    expect(project.find('[data-test="project-branch"]').text()).toContain('develop')
    expect(project.find('[data-test="project-waiting"]').text()).toContain('1')
    expect(project.find('[data-test="project-waiting"] .sr-only').text()).toContain('aguardando você')
  })

  it('o nome só é limitado a 60% quando a branch aparece ao lado', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'sem-git' }), makeProject({ id: 2, name: 'com-git' })]
    useGitStore(pinia).set(1, [])
    useGitStore(pinia).set(2, [makeGitRepo({ branch: 'develop' })])
    const [plain, withBranch] = mountSidebar().findAll('[data-test="project"]')
    const plainName = plain!.find('[data-test="project-name"]')
    expect(plain!.find('[data-test="project-branch"]').exists()).toBe(false)
    expect(plainName.classes()).toContain('truncate')
    expect(plainName.classes()).not.toContain('max-w-[60%]')
    expect(plainName.classes()).not.toContain('shrink-0')
    const branchName = withBranch!.find('[data-test="project-name"]')
    expect(withBranch!.find('[data-test="project-branch"]').exists()).toBe(true)
    expect(branchName.classes()).toContain('max-w-[60%]')
    expect(branchName.classes()).toContain('shrink-0')
  })

  it('mostra as conversas abertas numa lista só, sem repetir', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, display_state: 'running' }),
      makeSession({ session_id: 'b', project_id: 1 }),
    ])
    const w = mountSidebar()
    expect(w.findAll('[data-test="open"]').map((r) => r.attributes('href'))).toEqual(['/sessions/a', '/sessions/b'])
    expect(w.find('[data-test="running"]').exists()).toBe(false)
    expect(w.find('[data-test="recent"]').exists()).toBe(false)
  })

  it('a barra lateral começa com 288px', () => {
    expect(mountSidebar().find('nav').attributes('style')).toContain('width: 288px')
  })

  it('usa a largura salva', () => {
    sidebarWidth.value = 360
    expect(mountSidebar().find('nav').attributes('style')).toContain('width: 360px')
  })

  it('alça na borda direita redimensiona por arrasto e salva ao soltar', async () => {
    const w = mountSidebar()
    const handle = w.find('[data-test="sidebar-resize"]')
    expect(handle.attributes('role')).toBe('separator')
    expect(handle.attributes('aria-label')).toBe('Redimensionar menu lateral')
    await pointer(handle, 'pointerdown', 288)
    await pointer(handle, 'pointermove', 340)
    expect(w.find('nav').attributes('style')).toContain('width: 340px')
    expect(localStorage.getItem('maestro:sidebar-width')).toBeNull()
    await pointer(handle, 'pointerup', 340)
    expect(localStorage.getItem('maestro:sidebar-width')).toBe('340')
  })

  it('respeita os limites ao arrastar', async () => {
    const w = mountSidebar()
    const handle = w.find('[data-test="sidebar-resize"]')
    await pointer(handle, 'pointerdown', 288)
    await pointer(handle, 'pointermove', 2000)
    expect(w.find('nav').attributes('style')).toContain('width: 480px')
    await pointer(handle, 'pointermove', 0)
    expect(w.find('nav').attributes('style')).toContain('width: 240px')
  })

  it('setas do teclado ajustam de 16 em 16 e salvam; duplo clique volta ao padrão', async () => {
    const w = mountSidebar()
    const handle = w.find('[data-test="sidebar-resize"]')
    await handle.trigger('keydown', { key: 'ArrowRight' })
    expect(w.find('nav').attributes('style')).toContain('width: 304px')
    expect(localStorage.getItem('maestro:sidebar-width')).toBe('304')
    expect(handle.attributes('aria-valuenow')).toBe('304')
    await handle.trigger('keydown', { key: 'ArrowLeft' })
    await handle.trigger('keydown', { key: 'ArrowLeft' })
    expect(w.find('nav').attributes('style')).toContain('width: 272px')
    await handle.trigger('dblclick')
    expect(w.find('nav').attributes('style')).toContain('width: 288px')
    expect(localStorage.getItem('maestro:sidebar-width')).toBe('288')
  })

  it('Inbox, Dashboard, Conversas e Preferências têm ícone', () => {
    const w = mountSidebar()
    for (const id of ['nav-inbox', 'nav-dashboard', 'nav-conversations', 'preferences']) {
      expect(w.find(`[data-test="${id}"] svg`).exists(), id).toBe(true)
    }
  })

  it('projeto numa linha só: branch ao lado do nome', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
    const project = mountSidebar().find('[data-test="project"]')
    const name = project.find('[data-test="project-name"]')
    const branch = project.find('[data-test="project-branch"]')
    expect(branch.text()).toContain('develop')
    expect(branch.element.parentElement).toBe(name.element.parentElement)
    expect(branch.classes()).toContain('truncate')
  })

  it('mostra o círculo de execução no projeto que tem conversa rodando', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 }), makeProject({ id: 2, name: 'parado' })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [makeSession({ session_id: 'a', project_id: 1, display_state: 'running' })])
    sessions.setForProject(2, [makeSession({ session_id: 'b', project_id: 2 })])
    const [running, idle] = mountSidebar().findAll('[data-test="project"]')
    expect(running!.find('[data-test="project-running"]').exists()).toBe(true)
    expect(running!.find('[data-test="project-running"]').text()).toContain('em execução')
    expect(idle!.find('[data-test="project-running"]').exists()).toBe(false)
  })

  it('contadores do projeto não encolhem com nome e branch longos', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'um-nome-de-projeto-bem-comprido-mesmo' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'feat/uma-branch-com-nome-muito-longo' })])
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, display_state: 'running' }),
      makeSession({ session_id: 'b', project_id: 1, display_state: 'waiting', unread: true }),
    ])
    const project = mountSidebar().find('[data-test="project"]')
    expect(project.find('[data-test="project-name"]').classes()).toContain('truncate')
    expect(project.find('[data-test="project-waiting"]').classes()).toContain('shrink-0')
    expect(project.find('[data-test="project-running"]').classes()).toContain('shrink-0')
  })

  it('mostra "Conectado" no rodapé só com conexão', async () => {
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="connection-ok"]').text()).toBe('Conectado')
    socketStatus.current.value = 'reconnecting'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-test="connection-ok"]').exists()).toBe(false)
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
  beforeEach(() => { setCollapsed('project', 1, false); setCollapsed('project', 2, false) })

  it('não mostra a seta do projeto sem agrupadores', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    expect(mountSidebar().find('[data-test="project-toggle"]').exists()).toBe(false)
  })

  it('a seta tem alvo de 24px e o projeto sem filhos reserva o mesmo espaço', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 }), makeProject({ id: 2, name: 'blog' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    expect(w.find('[data-test="project-toggle"]').classes()).toContain('size-6')
    const spacer = w.findAll('[data-test="project"]')[1]!.element.previousElementSibling!
    expect(spacer.classList.contains('w-6')).toBe(true)
  })

  it('mostra as conversas abertas do projeto logo abaixo dele, recuadas, na ordem de Abertas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' }), makeProject({ id: 2, name: 'blog' })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'q', project_id: 1, title: 'Quieta', last_activity_at: 300 }),
      makeSession({ session_id: 'r', project_id: 1, title: 'Roda', display_state: 'running', last_activity_at: 200 }),
      makeSession({ session_id: 'p', project_id: 1, title: 'Pede', unread: true, last_activity_at: 100 }),
      makeSession({ session_id: 'f', project_id: 1, title: 'Fim', display_state: 'finished', finished: true }),
    ])
    sessions.setForProject(2, [makeSession({ session_id: 'b', project_id: 2, title: 'Do blog' })])
    const w = mountSidebar()
    const blocks = w.findAll('[data-test="project-sessions"]')
    expect(blocks).toHaveLength(2)
    expect(blocks[0]!.findAll('[data-test="project-session"]').map((r) => r.find('[data-test="row-title"]').text())).toEqual(['Pede', 'Roda', 'Quieta'])
    expect(blocks[0]!.classes()).toContain('pl-6')
    expect(blocks[0]!.find('[data-test="row-project"]').exists()).toBe(false)
    expect(blocks[1]!.find('[data-test="row-title"]').text()).toBe('Do blog')
    const projects = w.findAll('[data-test="project"]')
    const after = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(after(projects[0]!.element, blocks[0]!.element)).toBe(true)
    expect(after(blocks[0]!.element, projects[1]!.element)).toBe(true)
  })

  it('a lista geral Abertas continua com as mesmas conversas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    expect(w.findAll('[data-test="project-session"]')).toHaveLength(1)
    expect(w.findAll('[data-test="open"]')).toHaveLength(1)
  })

  it('projeto só com conversas ganha a seta, e recolher esconde as conversas', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    const toggle = w.find('[data-test="project-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(w.find('[data-test="project-sessions"]').exists()).toBe(false)
    expect(w.findAll('[data-test="open"]')).toHaveLength(1)
    await toggle.trigger('click')
    expect(w.find('[data-test="project-sessions"]').exists()).toBe(true)
  })

  it('conversa de agrupador aparece só dentro do agrupador, não solta sob o projeto', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useGroupsStore(pinia).groups = [makeGroup({ id: 1, project_id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'g', project_id: 1, group_id: 1, title: 'No grupo' }),
      makeSession({ session_id: 's', project_id: 1, group_id: null, title: 'Solta' }),
    ])
    const w = mountSidebar()
    expect(w.findAll('[data-test="project-session"]').map((r) => r.find('[data-test="row-title"]').text())).toEqual(['Solta'])
    expect(w.find('[data-test="sidebar-group"]').text()).toContain('No grupo')
    const block = w.find('[data-test="project-sessions"]').element
    const group = w.find('[data-test="sidebar-group"]').element
    expect(Boolean(block.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  })

  it('conversa que passa a esperar você sobe dentro do projeto', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const sessions = useSessionsStore(pinia)
    sessions.setForProject(1, [
      makeSession({ session_id: 'r', project_id: 1, title: 'Roda', display_state: 'running', last_activity_at: 200 }),
      makeSession({ session_id: 'c', project_id: 1, title: 'Cli', display_state: 'running', last_activity_at: 100 }),
    ])
    const w = mountSidebar()
    const c = sessions.find('c')!
    c.display_state = 'waiting'
    c.unread = true
    await flushPromises()
    expect(w.findAll('[data-test="project-session"]').map((r) => r.find('[data-test="row-title"]').text())).toEqual(['Cli', 'Roda'])
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
