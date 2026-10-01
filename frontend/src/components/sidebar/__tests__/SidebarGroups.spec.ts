import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'

import SidebarGroups from '../SidebarGroups.vue'
import { createAppRouter } from '../../../router'
import { isCollapsed, setCollapsed } from '../../../sidebarCollapse'
import { useGroupsStore } from '../../../stores/groups'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGroup, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
  setCollapsed('group', 1, false)
  setCollapsed('group', 2, false)
  useGroupsStore(pinia).groups = [makeGroup({ id: 1, name: 'Checkout' }), makeGroup({ id: 2, name: 'Parado' })]
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 'a1', group_id: 1, title: 'Carrinho', display_state: 'waiting', unread: true, last_activity_at: 20 }),
    makeSession({ session_id: 'a2', group_id: 1, title: 'Frete', display_state: 'running', last_activity_at: 10 }),
    makeSession({ session_id: 'a3', group_id: 1, title: 'Antiga', display_state: 'finished', last_activity_at: 5 }),
    makeSession({ session_id: 'b1', group_id: 2, title: 'Velha', display_state: 'finished' }),
  ])
})

async function mountGroups(path = '/projects/1') {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  return mount(SidebarGroups, { props: { projectId: 1 }, global: { plugins: [pinia, router] } })
}

describe('agrupadores no menu', () => {
  it('mostra o ativo e o parado, e o parado leva à tela do projeto', async () => {
    const wrapper = await mountGroups()
    expect(wrapper.findAll('[data-test="sidebar-group"]')).toHaveLength(1)
    const idle = wrapper.findAll('[data-test="sidebar-group-idle"]')
    expect(idle).toHaveLength(1)
    expect(idle[0]!.attributes('href')).toBe('/projects/1')
    expect(idle[0]!.text()).toContain('Parado')
    expect(idle[0]!.classes()).toContain('text-fg-subtle')
    expect(idle[0]!.classes()).not.toContain('opacity-50')
  })

  it('lista só as sessões ativas, com o caminho de cada uma', async () => {
    const wrapper = await mountGroups()
    const rows = wrapper.findAll('[data-test="sidebar-session"]')
    expect(rows.map((r) => r.attributes('href'))).toEqual(['/sessions/a1', '/sessions/a2'])
    expect(wrapper.text()).not.toContain('Antiga')
  })

  it('recolhe as sessões pela seta e guarda a escolha', async () => {
    const wrapper = await mountGroups()
    const toggle = wrapper.find('[data-test="group-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(wrapper.findAll('[data-test="sidebar-session"]')).toHaveLength(0)
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(isCollapsed('group', 1)).toBe(true)
  })

  it('conta as conversas que aguardam', async () => {
    const wrapper = await mountGroups()
    expect(wrapper.find('[data-test="group-waiting"]').text()).toBe('1')
  })

  it('esconde a contagem quando as que aguardam não têm nada novo', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'q1', group_id: 1, display_state: 'waiting', unread: false }),
    ])
    const wrapper = await mountGroups()
    expect(wrapper.find('[data-test="group-waiting"]').exists()).toBe(false)
  })

  it('marca a conversa da rota atual', async () => {
    const wrapper = await mountGroups('/sessions/a1')
    await flushPromises()
    const rows = wrapper.findAll('[data-test="sidebar-session"]')
    expect(rows[0]!.attributes('aria-current')).toBe('page')
    expect(rows[0]!.classes()).toContain('bg-card')
    expect(rows[1]!.attributes('aria-current')).toBeUndefined()
  })

  it('deixa o triângulo de "Sua vez" discreto quando a conversa não tem novidade', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'q1', group_id: 1, title: 'Lida', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'q2', group_id: 1, title: 'Nova', display_state: 'waiting', unread: true }),
    ])
    const wrapper = await mountGroups()
    const [read, unread] = wrapper.findAll('[data-test="sidebar-session"]')
    expect(read!.find('svg').classes()).toContain('stroke-fg-subtle')
    expect(unread!.find('svg').classes()).toContain('stroke-secondary')
    // the per-group counter stays orange
    expect(wrapper.find('[data-test="group-waiting"]').classes()).toContain('text-secondary')
    expect(wrapper.find('[data-test="group-waiting"] svg').classes()).toContain('stroke-secondary')
  })

  it('mantém o triângulo laranja quando há decisão pendente, mesmo sem novidade', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'p1', group_id: 1, title: 'Plano', display_state: 'waiting', unread: false, pending_kind: 'plan' }),
      makeSession({ session_id: 'p2', group_id: 1, title: 'Erro', display_state: 'waiting', unread: false, state: 'error' }),
    ])
    const wrapper = await mountGroups()
    for (const row of wrapper.findAll('[data-test="sidebar-session"]')) {
      expect(row.find('svg').classes()).toContain('stroke-secondary')
    }
  })
})
