import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AgentRegistry from '../AgentRegistry.vue'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, makeRun, routeFetch } from '../../../../test/factories'
import type { RegistryItem } from '../../../../types/org'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

const item = (overrides: Partial<RegistryItem> = {}): RegistryItem => ({
  key: 'erro-123', status: 'tratado', link: 'https://exemplo.com/1', note: 'Corrigido', created_at: 1_790_000_000, updated_at: 1_790_000_000, ...overrides,
})

async function mountRegistry(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({ 'GET /api/agents/1/registry': () => jsonResponse([item(), item({ key: 'erro-9', link: 'javascript:alert(1)' })]), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(AgentRegistry, { props: { agentId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return { wrapper, fetch }
}

describe('AgentRegistry', () => {
  it('lista os itens e só liga links http', async () => {
    const { wrapper } = await mountRegistry()
    const rows = wrapper.findAll('[data-test="item-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('erro-123')
    expect(rows[0]!.get('a').attributes('href')).toBe('https://exemplo.com/1')
    expect(rows[1]!.find('a').exists()).toBe(false)
    expect(rows[1]!.text()).toContain('javascript:alert(1)')
  })

  it('sem itens diz que não há nada registrado', async () => {
    const { wrapper } = await mountRegistry({ 'GET /api/agents/1/registry': () => jsonResponse([]) })
    expect(wrapper.get('[data-test="items-empty"]').text()).toBe('Nada registrado ainda.')
  })

  it('remove um item pela chave inteira na query', async () => {
    const { wrapper, fetch } = await mountRegistry({
      'GET /api/agents/1/registry': () => jsonResponse([item({ key: 'a/b c' })]),
      'DELETE /api/agents/1/registry?key=a%2Fb%20c': () => jsonResponse(undefined, 204),
    })
    await wrapper.get('[data-test="item-remove"]').trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/1/registry?key=a%2Fb%20c' && init?.method === 'DELETE')).toBe(true)
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(0)
  })

  it('mostra o erro ao remover', async () => {
    const { wrapper } = await mountRegistry({ 'DELETE /api/agents/1/registry?key=erro-123': () => jsonResponse({ detail: 'Item não encontrado.' }, 404) })
    await wrapper.findAll('[data-test="item-remove"]')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="items-error"]').attributes('role')).toBe('alert')
  })

  it('relê o registro quando uma execução do agente muda de estado', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, last_run: makeRun({ outcome: 'running' }) })]
    let items: RegistryItem[] = []
    const { wrapper } = await mountRegistry({ 'GET /api/agents/1/registry': () => jsonResponse(items) })
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(0)
    items = [item()]
    useOrgStore(pinia).agents[0]!.last_run = makeRun({ outcome: 'concluded', ended_at: 1_790_000_100 })
    await flushPromises()
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(1)
  })
})
