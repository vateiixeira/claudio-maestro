import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'

import SidebarGroups from '../SidebarGroups.vue'
import { createAppRouter } from '../../../router'
import { clockNow } from '../../../minuteClock'
import { isCollapsed, setCollapsed } from '../../../sidebarCollapse'
import { useGroupsStore } from '../../../stores/groups'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { makeGroup, makeProject, jsonResponse, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())
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

async function mountGroups(path = '/projects/1', attach = false) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  return mount(SidebarGroups, {
    props: { projectId: 1 },
    global: { plugins: [pinia, router] },
    ...(attach ? { attachTo: document.body } : {}),
  })
}

describe('agrupadores no menu', () => {
  it('mostra só o agrupador com conversa ativa e oculta o parado', async () => {
    const wrapper = await mountGroups()
    expect(wrapper.findAll('[data-test="sidebar-group"]')).toHaveLength(1)
    expect(wrapper.find('[data-test="sidebar-group-idle"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Checkout')
    expect(wrapper.text()).not.toContain('Parado')
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

  it('em "Sua vez" mostra o tempo desde a última interação; em execução não', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-02T12:00:00Z'))
    clockNow.value = Date.now()
    const now = Math.floor(Date.now() / 1000)
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'w1', group_id: 1, title: 'Aguarda', display_state: 'waiting', last_activity_at: now - 3 * 60 }),
      makeSession({ session_id: 'r1', group_id: 1, title: 'Roda', display_state: 'running', last_activity_at: now - 3 * 60 }),
    ])
    const wrapper = await mountGroups()
    const [waiting, running] = wrapper.findAll('[data-test="sidebar-session"]')
    expect(waiting!.find('[data-test="row-age"]').text()).toBe('3 min')
    expect(waiting!.find('[data-test="row-age"]').attributes('title')).toContain('Última interação')
    expect(running!.find('[data-test="row-age"]').exists()).toBe(false)
  })

  it('mostra o agrupador criado em outro projeto com as conversas de todos, marcando as de fora', async () => {
    setCollapsed('group', 3, false)
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'api' }), makeProject({ id: 2, name: 'web' })]
    useGroupsStore(pinia).groups = [makeGroup({ id: 3, project_id: 2, name: 'Pagamento' })]
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'p1', project_id: 1, group_id: 3, title: 'Backend', display_state: 'running' })])
    useSessionsStore(pinia).setForProject(2, [makeSession({ session_id: 'p2', project_id: 2, group_id: 3, title: 'Tela', display_state: 'running' })])
    const w = await mountGroups()
    expect(w.findAll('[data-test="sidebar-group"]')).toHaveLength(1)
    expect(w.findAll('[data-test="sidebar-session"]')).toHaveLength(2)
    const foreign = w.findAll('[data-test="group-session-project"]')
    expect(foreign).toHaveLength(1)
    expect(foreign[0]!.text()).toBe('web')
  })

  it('remove o agrupador ativo pelo botão da linha, depois de confirmar', async () => {
    const fetchMock = routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) })
    vi.stubGlobal('fetch', fetchMock)
    const w = await mountGroups()
    expect(w.find('[data-test="group-confirm-remove"]').exists()).toBe(false)
    const button = w.findAll('[data-test="sidebar-group-remove"]')[0]!
    expect(button.attributes('aria-label')).toBe('Remover o agrupador Checkout')
    await button.trigger('click')
    expect(w.find('[data-test="group-confirm-remove"]').text()).toContain('Remover o agrupador Checkout?')
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/groups/1' && init?.method === 'DELETE')).toBe(true)
    expect(useGroupsStore(pinia).byId(1)).toBeUndefined()
  })

  it('Esc cancela a remoção devolvendo o foco ao botão da linha', async () => {
    const w = await mountGroups('/projects/1', true)
    const buttons = w.findAll('[data-test="sidebar-group-remove"]')
    expect(buttons).toHaveLength(1)
    await buttons[0]!.trigger('click')
    expect(w.find('[data-test="group-confirm-remove"]').text()).toContain('Remover o agrupador Checkout?')
    await w.find('[data-test="group-confirm-remove"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[data-test="group-confirm-remove"]').exists()).toBe(false)
    expect(document.activeElement).toBe(w.findAll('[data-test="sidebar-group-remove"]')[0]!.element)
  })

  it('mostra o erro quando a remoção falha: a confirmação fecha e o agrupador fica', async () => {
    const fetchMock = routeFetch({ 'DELETE /api/groups/1': () => jsonResponse({ detail: 'Falhou' }, 500) })
    vi.stubGlobal('fetch', fetchMock)
    const w = await mountGroups()
    await w.findAll('[data-test="sidebar-group-remove"]')[0]!.trigger('click')
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="group-confirm-remove"]').exists()).toBe(false)
    expect(useGroupsStore(pinia).byId(1)).toBeDefined()
    expect(w.findAll('[data-test="sidebar-group"]')).toHaveLength(1)
    expect(w.find('[role="alert"]').text()).toBe('Falhou')
    // opening a new confirmation clears the old message
    await w.findAll('[data-test="sidebar-group-remove"]')[0]!.trigger('click')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })
})
