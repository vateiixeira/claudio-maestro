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
import { useUpdatesStore } from '../../../stores/updates'
import { setCollapsed, setSectionCollapsed, setSectionOpened } from '../../../sidebarCollapse'
import { sidebarWidth } from '../../../sidebarWidthPref'
import { makeGitRepo, makeGroup, makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.removeItem('maestro:sidebar-width')
  setSectionOpened('others', false)
  setSectionCollapsed('review', false)
  setSectionOpened('later', false)
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
  it('separa o menu da conversa com a borda forte à direita', () => {
    const classes = mountSidebar().get('nav[aria-label="Navegação"]').classes()
    expect(classes).toContain('border-r')
    expect(classes).toContain('border-line-strong')
    expect(classes).not.toContain('border-line')
  })

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

  it('não conta na Inbox nem no projeto a conversa marcada, mesmo não lida', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: true, mark: 'on_hold' }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: true, mark: 'review' }),
    ])
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="inbox-count"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="project-waiting"]').exists()).toBe(false)
  })

  it('conta a conversa marcada que tem pedido real do Claude', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', mark: 'blocked', pending_kind: 'question' }),
    ])
    const wrapper = mountSidebar()
    expect(wrapper.find('[data-test="inbox-count"]').text()).toBe('1')
    expect(wrapper.find('[data-test="project-waiting"]').text()).toContain('1')
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
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'b', project_id: 2 })])
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

  it('não repete as conversas numa lista Abertas: cada uma aparece uma vez, sob o projeto', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1, display_state: 'running' }),
      makeSession({ session_id: 'b', project_id: 1 }),
    ])
    const w = mountSidebar()
    expect(w.find('[data-test="sidebar-open"]').exists()).toBe(false)
    expect(w.find('[data-test="open"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Abertas')
    expect(w.findAll('a[href="/sessions/a"]')).toHaveLength(1)
    expect(w.findAll('a[href="/sessions/b"]')).toHaveLength(1)
    expect(w.findAll('[data-test="project-session"]').map((r) => r.attributes('href'))).toEqual(['/sessions/a', '/sessions/b'])
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
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
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

  it('não mostra a seta do projeto sem conversa nem agrupadores', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    expect(mountSidebar().find('[data-test="project-toggle"]').exists()).toBe(false)
  })

  it('a seta tem alvo de 24px e fica depois do link do projeto, no fim da linha', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    const toggle = w.find('[data-test="project-toggle"]')
    expect(toggle.classes()).toContain('size-6')
    const link = w.find('[data-test="project"]').element
    expect(Boolean(link.compareDocumentPosition(toggle.element) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
    expect(link.parentElement!.lastElementChild).toBe(toggle.element)
  })

  it('mostra as conversas abertas do projeto logo abaixo dele, recuadas, com o que espera você primeiro', () => {
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
    expect(blocks[0]!.classes()).toContain('border-l')
    expect(blocks[0]!.classes()).toContain('ml-[14px]')
    expect(blocks[0]!.findAll('[data-test="project-session"]').every((r) => r.classes().includes('min-h-7'))).toBe(true)
    const wrappers = w.findAll('[data-test="project"]').map((p) => p.element.parentElement!)
    expect(wrappers[0]!.classList.contains('mt-1.5')).toBe(false)
    expect(wrappers[1]!.classList.contains('mt-1.5')).toBe(true)
    expect(blocks[0]!.find('[data-test="row-project"]').exists()).toBe(false)
    expect(blocks[1]!.find('[data-test="row-title"]').text()).toBe('Do blog')
    const projects = w.findAll('[data-test="project"]')
    const after = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(after(projects[0]!.element, blocks[0]!.element)).toBe(true)
    expect(after(blocks[0]!.element, projects[1]!.element)).toBe(true)
  })

  it('projeto só com conversas ganha a seta, e recolher esconde as conversas', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    const toggle = w.find('[data-test="project-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(w.find('[data-test="project-sessions"]').exists()).toBe(false)
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
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const router = createAppRouter(createMemoryHistory())
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })
    await wrapper.find('[data-test="project"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/projects/1')
  })
})

describe('menu lateral: Em andamento e Outros projetos', () => {
  const heads = (w: ReturnType<typeof mountSidebar>) => w.findAll('[data-test="section-title"]').map((e) => e.text())

  function twoProjects() {
    useProjectsStore(pinia).projects = [
      makeProject({ id: 1, name: 'loja-online' }),
      makeProject({ id: 2, name: 'blog', color: '#112233' }),
      makeProject({ id: 3, name: 'api' }),
    ]
    useGitStore(pinia).set(2, [makeGitRepo({ branch: 'develop' })])
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
  }

  it('Em andamento tem só os projetos com conversa aberta; os demais ficam recolhidos em uma linha', () => {
    twoProjects()
    const w = mountSidebar()
    expect(heads(w)).toEqual(['Em andamento', 'Outros projetos'])
    expect(w.findAll('[data-test="project"]').map((p) => p.find('[data-test="project-name"]').text())).toEqual(['loja-online'])
    const toggle = w.get('[data-test="others-toggle"]')
    expect(toggle.text()).toContain('2 sem conversa aberta')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.classes()).toContain('text-fg-subtle')
    expect(w.findAll('[data-test="other-project"]')).toHaveLength(0)
  })

  it('aberta, mostra uma linha por projeto: quadradinho, nome mais claro e sem negrito, branch em mono; e guarda o estado', async () => {
    twoProjects()
    const w = mountSidebar()
    await w.get('[data-test="others-toggle"]').trigger('click')
    expect(w.get('[data-test="others-toggle"]').attributes('aria-expanded')).toBe('true')
    const rows = w.findAll('[data-test="other-project"]')
    expect(rows.map((r) => r.attributes('href'))).toEqual(['/projects/2', '/projects/3'])
    const blog = rows[0]!
    expect(blog.get('[data-test="project-color"]').attributes('style')).toContain('background-color')
    const name = blog.get('[data-test="other-project-name"]')
    expect(name.text()).toBe('blog')
    expect(name.classes()).toContain('text-fg-muted')
    expect(name.classes()).not.toContain('font-medium')
    const branch = blog.get('[data-test="other-project-branch"]')
    expect(branch.text()).toContain('develop')
    expect(branch.classes()).toContain('font-mono')
    expect(rows[1]!.find('[data-test="other-project-branch"]').exists()).toBe(false)
    expect(JSON.parse(localStorage.getItem('maestro:sidebar-collapsed')!).section).toContain('+others')
    await w.get('[data-test="others-toggle"]').trigger('click')
    expect(w.findAll('[data-test="other-project"]')).toHaveLength(0)
  })

  it('lembra de Outros projetos aberto', () => {
    twoProjects()
    setSectionOpened('others', true)
    expect(mountSidebar().findAll('[data-test="other-project"]')).toHaveLength(2)
  })

  it('o projeto sobe para Em andamento quando ganha conversa e desce quando ela termina', async () => {
    twoProjects()
    setSectionOpened('others', true)
    const w = mountSidebar()
    const sessions = useSessionsStore(pinia)
    expect(w.findAll('[data-test="other-project"]')).toHaveLength(2)
    sessions.setForProject(3, [makeSession({ session_id: 'n', project_id: 3, title: 'Nova' })])
    await flushPromises()
    expect(w.findAll('[data-test="project"]').map((p) => p.find('[data-test="project-name"]').text())).toEqual(['loja-online', 'api'])
    expect(w.findAll('[data-test="other-project"]').map((r) => r.get('[data-test="other-project-name"]').text())).toEqual(['blog'])
    sessions.find('n')!.display_state = 'finished'
    await flushPromises()
    expect(w.findAll('[data-test="project"]')).toHaveLength(1)
    expect(w.findAll('[data-test="other-project"]')).toHaveLength(2)
  })

  it('Outros projetos some quando todos têm conversa aberta', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'a', project_id: 1 })])
    const w = mountSidebar()
    expect(heads(w)).toEqual(['Em andamento'])
    expect(w.find('[data-test="others-toggle"]').exists()).toBe(false)
  })

  it('sem nenhuma conversa aberta, diz isso em Em andamento e deixa os projetos recolhidos', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    const w = mountSidebar()
    expect(w.get('[data-test="no-open"]').text()).toBe('Nenhuma conversa aberta')
    expect(w.get('[data-test="others-toggle"]').text()).toContain('1 sem conversa aberta')
  })

  it('mostra o projeto da tela atual mesmo recolhido em Outros projetos', async () => {
    twoProjects()
    const router = createAppRouter(createMemoryHistory())
    await router.push('/projects/3')
    const w = mount(AppSidebar, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(w.findAll('[data-test="other-project"]')).toHaveLength(2)
    const current = w.get('[data-test="other-project"][href="/projects/3"]')
    expect(current.attributes('aria-current')).toBe('page')
    expect(w.get('[data-test="other-project"][href="/projects/2"]').attributes('aria-current')).toBeUndefined()
    expect(w.get('[data-test="others-toggle"]').attributes('aria-expanded')).toBe('true')
  })

  it('o projeto com pasta indisponível em Outros projetos continua marcado', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'sumiu', available: false })]
    setSectionOpened('others', true)
    const row = mountSidebar().get('[data-test="other-project"]')
    expect(row.attributes('data-available')).toBe('false')
    expect(row.text()).toContain('pasta indisponível')
  })

  it('as faixas Para revisar e Depois continuam, depois dos projetos', () => {
    twoProjects()
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', project_id: 1 }),
      makeSession({ session_id: 'r', project_id: 1, mark: 'review' }),
      makeSession({ session_id: 'd', project_id: 1, mark: 'on_hold' }),
    ])
    const w = mountSidebar()
    expect(w.get('[data-test="lane-review"]').text()).toContain('Para revisar')
    expect(w.get('[data-test="lane-later"]').text()).toContain('Depois')
    expect(w.findAll('[data-test="lane-review-row"]').map((r) => r.attributes('href'))).toEqual(['/sessions/r'])
    const after = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(after(w.get('[data-test="others-toggle"]').element, w.get('[data-test="lane-review"]').element)).toBe(true)
  })

  it('separa as seções com 22px e sem borda', () => {
    twoProjects()
    const scroller = mountSidebar().get('[data-test="sidebar-sections"]')
    expect(scroller.classes()).toContain('gap-[22px]')
    expect(scroller.classes().filter((c) => c.startsWith('border'))).toEqual([])
  })
})

const RELEASES = 'https://github.com/vateiixeira/claudio-maestro/releases'
function updateState(overrides = {}) {
  return {
    enabled: true,
    current: '0.1.0',
    available: false,
    latest: null,
    checked_at: 1791303600,
    releases_url: RELEASES,
    ...overrides,
  }
}

describe('versão no rodapé do menu', () => {
  beforeEach(() => localStorage.removeItem('maestro:update-dismissed'))

  it('esconde a linha antes de o backend responder', () => {
    expect(mountSidebar().find('[data-test="app-version"]').exists()).toBe(false)
  })

  it('mostra só a versão, com link para a release instalada', async () => {
    useUpdatesStore().apply(updateState())
    const wrapper = mountSidebar()
    await nextTick()
    const link = wrapper.get('[data-test="app-version"] a')
    expect(link.text()).toBe('v0.1.0')
    expect(link.attributes('href')).toBe(`${RELEASES}/tag/v0.1.0`)
    expect(link.attributes('target')).toBe('_blank')
    expect(wrapper.find('[data-test="update-notice"]').exists()).toBe(false)
  })

  it('avisa da versão nova e abre o modal', async () => {
    const updates = useUpdatesStore()
    updates.apply(updateState({ available: true, latest: { version: '0.2.0', url: `${RELEASES}/tag/v0.2.0`, notes: '', published_at: null } }))
    const wrapper = mountSidebar()
    await nextTick()
    const notice = wrapper.get('[data-test="update-notice"]')
    expect(notice.text()).toContain('v0.1.0')
    expect(notice.text()).toContain('0.2.0 disponível')
    await notice.trigger('click')
    expect(updates.modalOpen).toBe(true)
  })

  it('a linha da versão trunca em vez de quebrar', async () => {
    useUpdatesStore().apply(updateState())
    const wrapper = mountSidebar()
    await nextTick()
    expect(wrapper.get('[data-test="app-version"] a').classes()).toContain('truncate')
  })
})
