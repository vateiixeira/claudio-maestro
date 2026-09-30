import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ProjectGroups from '../ProjectGroups.vue'
import { createAppRouter } from '../../../router'
import { useGroupsStore } from '../../../stores/groups'
import { useNewConversationStore } from '../../../stores/newConversation'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => { pinia = createPinia(); setActivePinia(pinia) })
afterEach(() => vi.unstubAllGlobals())

function mountGroups(available = true) {
  const router = createAppRouter(createMemoryHistory())
  return mount(ProjectGroups, { props: { projectId: 1, available }, global: { plugins: [pinia, router] }, attachTo: document.body })
}

describe('agrupadores na tela do projeto', () => {
  it('sem agrupadores mostra o botão e a explicação', () => {
    const w = mountGroups()
    expect(w.find('[data-test="groups-empty"]').exists()).toBe(true)
    expect(w.find('[data-test="group-new"]').exists()).toBe(true)
  })

  it('mostra cada agrupador com contagem e todas as sessões, mais recente primeiro', () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'Checkout' }), makeGroup({ id: 2, name: 'Vazio', created_at: 1 })]
    useSessionsStore().setForProject(1, [
      makeSession({ session_id: 'a', group_id: 1, last_activity_at: 10, title: 'Velha' }),
      makeSession({ session_id: 'b', group_id: 1, last_activity_at: 20, title: 'Nova', display_state: 'finished' }),
      makeSession({ session_id: 'c', group_id: null }),
    ])
    const w = mountGroups()
    const names = w.findAll('[data-test="group-name"]').map((n) => n.text())
    expect(names).toEqual(['Checkout', 'Vazio'])
    expect(w.findAll('[data-test="group-count"]').map((n) => n.text())).toEqual(['2 conversas · 1 ativa', 'Nenhuma conversa'])
    const first = w.findAll('[data-test="group-section"]')[0]!
    expect(first.findAll('[data-test="row-link"]').map((l) => l.text())).toEqual(['Nova', 'Velha'])
  })

  it('recolhe e expande', async () => {
    useGroupsStore().groups = [makeGroup()]
    useSessionsStore().setForProject(1, [makeSession({ group_id: 1 })])
    const w = mountGroups()
    const toggle = w.find('[data-test="group-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="row-link"]').exists()).toBe(false)
  })

  it('cria com Enter e mostra o erro sem fechar o campo', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/projects/1/groups': (init) => JSON.parse(String(init?.body)).name === 'dup'
        ? jsonResponse({ detail: 'Já existe um agrupador com esse nome neste projeto.' }, 409)
        : jsonResponse(makeGroup({ id: 7, name: 'Novo' }), 201),
    }))
    const w = mountGroups()
    await w.find('[data-test="group-new"]').trigger('click')
    const input = w.find('[data-test="group-new-name"]')
    await input.setValue('dup')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('Já existe')
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(true)
    await input.setValue('Novo')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(false)
    expect(useGroupsStore().byId(7)?.name).toBe('Novo')
  })

  it('Esc fecha o campo de criação sem criar', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const w = mountGroups()
    await w.find('[data-test="group-new"]').trigger('click')
    await w.find('[data-test="group-new-name"]').trigger('keydown', { key: 'Escape' })
    expect(w.find('[data-test="group-new-name"]').exists()).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('renomeia com Enter', async () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'A' })]
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/groups/1': () => jsonResponse(makeGroup({ id: 1, name: 'B' })) }))
    const w = mountGroups()
    await w.find('[data-test="group-rename"]').trigger('click')
    const input = w.find('[data-test="group-rename-input"]')
    await input.setValue('B')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('[data-test="group-name"]').text()).toBe('B')
  })

  it('remove com confirmação, foco em Cancelar e texto com a contagem', async () => {
    useGroupsStore().groups = [makeGroup({ id: 1, name: 'A' })]
    useSessionsStore().setForProject(1, [makeSession({ session_id: 'a', group_id: 1 }), makeSession({ session_id: 'b', group_id: 1 })])
    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) }))
    const w = mountGroups()
    await w.find('[data-test="group-remove"]').trigger('click')
    await flushPromises()
    const dialog = w.find('[data-test="group-confirm-remove"]')
    expect(dialog.text()).toContain('Remover o agrupador A?')
    expect(dialog.text()).toContain('As 2 conversas voltam a ficar soltas; nenhuma é apagada.')
    expect(document.activeElement).toBe(w.find('[data-test="group-confirm-cancel"]').element)
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(useGroupsStore().groups).toEqual([])
  })

  it('"＋ Conversa" abre a nova conversa no agrupador; desabilitado com a pasta indisponível', async () => {
    useGroupsStore().groups = [makeGroup({ id: 3 })]
    const w = mountGroups()
    await w.find('[data-test="group-new-session"]').trigger('click')
    const nc = useNewConversationStore()
    expect([nc.isOpen, nc.presetProjectId, nc.presetGroupId]).toEqual([true, 1, 3])
    const off = mountGroups(false)
    expect(off.find('[data-test="group-new-session"]').attributes('disabled')).toBeDefined()
  })
})
