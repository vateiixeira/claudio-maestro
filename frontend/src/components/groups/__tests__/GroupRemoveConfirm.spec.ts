import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GroupRemoveConfirm from '../GroupRemoveConfirm.vue'
import { useGroupsStore } from '../../../stores/groups'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useGroupsStore(pinia).groups = [makeGroup({ id: 1, name: 'Checkout' })]
})
afterEach(() => vi.unstubAllGlobals())

function mountConfirm(sessions = [makeSession({ session_id: 'a', group_id: 1 })]) {
  return mount(GroupRemoveConfirm, {
    props: { group: makeGroup({ id: 1, name: 'Checkout' }), sessions },
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
}

describe('confirmação de remover agrupador', () => {
  it('diz o que acontece com as conversas, inclusive de vários projetos', () => {
    expect(mountConfirm([]).text()).toContain('O agrupador está vazio.')
    const mixed = [makeSession({ session_id: 'a', project_id: 1 }), makeSession({ session_id: 'b', project_id: 2 })]
    const w = mountConfirm(mixed)
    expect(w.text()).toContain('Remover o agrupador Checkout?')
    expect(w.text()).toContain('As 2 conversas, de 2 projetos, voltam a ficar soltas; nenhuma é apagada.')
  })

  it('foca o Cancelar e Esc cancela', async () => {
    const w = mountConfirm()
    expect(document.activeElement).toBe(w.find('[data-test="group-confirm-cancel"]').element)
    await w.find('[data-test="group-confirm-remove"]').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('cancel')).toHaveLength(1)
  })

  it('Remover agrupador chama a API e avisa', async () => {
    const fetchMock = routeFetch({ 'DELETE /api/groups/1': () => new Response(null, { status: 204 }) })
    vi.stubGlobal('fetch', fetchMock)
    const w = mountConfirm()
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/groups/1' && init?.method === 'DELETE')).toBe(true)
    expect(w.emitted('removed')).toHaveLength(1)
    expect(useGroupsStore(pinia).byId(1)).toBeUndefined()
  })

  it('erro da API vira error e cancel, sem sumir com o agrupador', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'DELETE /api/groups/1': () => jsonResponse({ detail: 'Falhou' }, 500) }))
    const w = mountConfirm()
    await w.find('[data-test="group-confirm-ok"]').trigger('click')
    await flushPromises()
    expect(w.emitted('error')).toEqual([['Falhou']])
    expect(w.emitted('cancel')).toHaveLength(1)
    expect(useGroupsStore(pinia).byId(1)).toBeDefined()
  })
})
