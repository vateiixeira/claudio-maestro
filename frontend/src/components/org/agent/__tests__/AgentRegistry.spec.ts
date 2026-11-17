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
  key: 'chamado:1042', status: 'aguardando', link: null, note: null, created_at: 1_790_000_000, updated_at: 1_790_000_000, ...overrides,
})

const PR = 'https://github.com/exemplo/loja-demo/pull/12'
const sample = (): RegistryItem[] => [
  item({ key: 'chamado:1042', status: 'aguardando', updated_at: 1_790_000_300 }),
  item({ key: 'chamado:1043', status: 'pr-aberto', link: PR, note: 'Corrigido o arredondamento do frete.', updated_at: 1_790_000_400 }),
  item({ key: 'chamado:1038', status: 'descartado', updated_at: 1_790_000_100 }),
  item({ key: 'chamado:1039', status: 'descartado', updated_at: 1_790_000_200 }),
]

async function mountRegistry(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({ 'GET /api/agents/1/registry': () => jsonResponse(sample()), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(AgentRegistry, { props: { agentId: 1 }, global: { plugins: [pinia] } })
  await flushPromises()
  return { wrapper, fetch }
}

describe('AgentRegistry', () => {
  it('lista os itens do mais recente ao mais antigo', async () => {
    const { wrapper } = await mountRegistry()
    expect(wrapper.findAll('[data-test="item-key"]').map((k) => k.text())).toEqual(['chamado:1043', 'chamado:1042', 'chamado:1039', 'chamado:1038'])
  })

  it('mostra um chip por situação, do mais frequente ao menos, e começa em Todos', async () => {
    const { wrapper } = await mountRegistry()
    const chips = wrapper.findAll('[data-test="registry-chip"]')
    expect(chips.map((c) => c.text())).toEqual(['Todos4', 'Descartado2', 'Aguardando1', 'PR aberto1'])
    expect(chips[0]!.attributes('data-status')).toBe('')
    expect(chips[0]!.attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-test="registry-filter"]').exists()).toBe(true)
  })

  it('filtra pela situação e volta a Todos ao clicar de novo', async () => {
    const { wrapper } = await mountRegistry()
    const chip = () => wrapper.findAll('[data-test="registry-chip"]')[1]!
    await chip().trigger('click')
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(2)
    expect(chip().attributes('aria-pressed')).toBe('true')
    await chip().trigger('click')
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(4)
    expect(wrapper.findAll('[data-test="registry-chip"]')[0]!.attributes('aria-pressed')).toBe('true')
  })

  it('busca na chave e na nota, sem diferenciar maiúsculas', async () => {
    const { wrapper } = await mountRegistry()
    const search = wrapper.get('[data-test="registry-search"]')
    await search.setValue('FRETE')
    expect(wrapper.findAll('[data-test="item-key"]').map((k) => k.text())).toEqual(['chamado:1043'])
    await search.setValue('1042')
    expect(wrapper.findAll('[data-test="item-key"]').map((k) => k.text())).toEqual(['chamado:1042'])
    await search.setValue('nada disso')
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(0)
    expect(wrapper.get('[data-test="registry-no-match"]').text()).toBe('Nenhum item com esse filtro.')
  })

  it('desenha a situação com o tom e o texto certos', async () => {
    const { wrapper } = await mountRegistry()
    const byKey = (key: string) => wrapper.findAll('[data-test="item-row"]').find((r) => r.get('[data-test="item-key"]').text() === key)!.get('[data-test="item-status"]')
    expect(byKey('chamado:1042').attributes('data-tone')).toBe('waiting')
    expect(byKey('chamado:1042').text()).toBe('Aguardando')
    expect(byKey('chamado:1043').attributes('data-tone')).toBe('info')
    expect(byKey('chamado:1043').text()).toBe('PR aberto')
    expect(byKey('chamado:1038').attributes('data-tone')).toBe('muted')
    expect(byKey('chamado:1038').text()).toBe('Descartado')
  })

  it('liga o link http com rel seguro e o texto resumido', async () => {
    const { wrapper } = await mountRegistry()
    const link = wrapper.get('[data-test="item-link"]')
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('href')).toBe(PR)
    expect(link.text()).toBe('loja-demo · PR #12')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener noreferrer')
  })

  it('mostra como texto, sem <a>, o link que não é http', async () => {
    const { wrapper } = await mountRegistry({ 'GET /api/agents/1/registry': () => jsonResponse([item({ key: 'x:1', link: 'javascript:alert(1)' }), item({ key: 'x:2', link: '/home/x/arquivo' })]) })
    expect(wrapper.find('a').exists()).toBe(false)
    const links = wrapper.findAll('[data-test="item-link"]')
    expect(links.map((l) => l.element.tagName)).toEqual(['SPAN', 'SPAN'])
    expect(links.map((l) => l.text()).sort()).toEqual(['/home/x/arquivo', 'javascript:alert(1)'])
  })

  it('guarda a chave e a nota inteiras no title', async () => {
    const { wrapper } = await mountRegistry()
    const row = wrapper.findAll('[data-test="item-row"]')[0]!
    expect(row.get('[data-test="item-key"]').attributes('title')).toBe('chamado:1043')
    expect(row.get('[data-test="item-note"]').attributes('title')).toBe('Corrigido o arredondamento do frete.')
    expect(row.get('[data-test="item-date"]').text()).not.toBe('')
  })

  it('remove o item, que some junto com o chip da situação', async () => {
    const { wrapper, fetch } = await mountRegistry({ 'DELETE /api/agents/1/registry?key=chamado%3A1042': () => jsonResponse(undefined, 204) })
    const remove = wrapper.findAll('[data-test="item-row"]').find((r) => r.text().includes('chamado:1042'))!.get('[data-test="item-remove"]')
    expect(remove.attributes('aria-label')).toBe('Remover chamado:1042 do registro')
    await remove.trigger('click')
    await flushPromises()
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents/1/registry?key=chamado%3A1042' && init?.method === 'DELETE')).toBe(true)
    expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(3)
    expect(wrapper.findAll('[data-test="registry-chip"]').map((c) => c.text())).not.toContain('Aguardando1')
    expect(wrapper.findAll('[data-test="registry-chip"]')).toHaveLength(3)
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
    const { wrapper } = await mountRegistry({ 'DELETE /api/agents/1/registry?key=chamado%3A1043': () => jsonResponse({ detail: 'Item não encontrado.' }, 404) })
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
