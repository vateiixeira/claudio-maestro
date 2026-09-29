import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
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
import { useNewConversationStore } from '../../../stores/newConversation'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGitRepo, makeProject, makeSession } from '../../../test/factories'

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
      makeSession({ session_id: 'a', display_state: 'waiting' }),
      makeSession({ session_id: 'b', display_state: 'waiting' }),
      makeSession({ session_id: 'c', display_state: 'running' }),
    ])
    expect(mountSidebar().find('[data-test="inbox-count"]').text()).toBe('2')
  })

  it('lista projetos com cor, branch e aguardando, sem conversas aninhadas', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
    useSessionsStore(pinia).setForProject(1, [makeSession({ display_state: 'waiting' })])

    const project = mountSidebar().find('[data-test="project"]')
    expect(project.attributes('href')).toBe('/projects/1')
    expect(project.find('[data-test="project-name"]').text()).toBe('loja-online')
    expect(project.find('[data-test="project-branch"]').text()).toContain('develop')
    expect(project.find('[data-test="project-waiting"]').text()).toContain('1')
    expect(mountSidebar().find('[data-test="session"]').exists()).toBe(false)
  })

  it('mostra as 5 conversas abertas mais recentemente', () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, Array.from({ length: 7 }, (_, i) =>
      makeSession({ session_id: `s${i}`, title: `T${i}`, last_seen_at: 1_790_000_000 + i }),
    ).concat([makeSession({ session_id: 'nunca', last_seen_at: null })]))

    const recent = mountSidebar().findAll('[data-test="recent"]')
    expect(recent.map((r) => r.text())).toEqual(['T6', 'T5', 'T4', 'T3', 'T2'])
    expect(recent[0]!.attributes('href')).toBe('/sessions/s6')
  })

  it('marca com aria-current só o link da conversa aberta em Recentes', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1 })]
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', title: 'A', last_seen_at: 1_790_000_002 }),
      makeSession({ session_id: 's2', title: 'B', last_seen_at: 1_790_000_001 }),
    ])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s2')
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })

    const links = wrapper.findAll('[data-test="recent"]')
    expect(links.map((l) => l.attributes('aria-current'))).toEqual([undefined, 'page'])
  })

  it('"Nova conversa" abre o modal', async () => {
    const wrapper = mountSidebar()
    await wrapper.find('[data-test="nav-new"]').trigger('click')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
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
