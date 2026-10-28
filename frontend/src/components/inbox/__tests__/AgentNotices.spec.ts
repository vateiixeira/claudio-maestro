import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentNotices from '../AgentNotices.vue'
import { createAppRouter } from '../../../router'
import { useOrgStore } from '../../../stores/org'
import { jsonResponse, makeAgent, makeNotice, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 1, name: 'Triagem', project_id: 3 }), makeAgent({ id: 2, name: 'Filmes' })]
})
afterEach(() => vi.unstubAllGlobals())

async function mountNotices() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  return mount(AgentNotices, { global: { plugins: [pinia, router] } })
}

describe('AgentNotices', () => {
  it('some sem avisos não lidos', async () => {
    const store = useOrgStore(pinia)
    expect((await mountNotices()).find('[data-test="agent-notices"]').exists()).toBe(false)
    store.notices = [makeNotice({ id: 1, read_at: 1_790_000_100 })]
    expect((await mountNotices()).find('[data-test="agent-notices"]').exists()).toBe(false)
  })

  it('lista só os não lidos, com o nome do agente e o texto', async () => {
    useOrgStore(pinia).notices = [
      makeNotice({ id: 1, agent_id: 1, text: 'Tratei 2 erros.' }),
      makeNotice({ id: 2, agent_id: 2, text: 'Já lido.', read_at: 5 }),
      makeNotice({ id: 3, agent_id: 2, text: 'Dois filmes novos.' }),
    ]
    const w = await mountNotices()
    const items = w.findAll('[data-test="agent-notice"]')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('Triagem')
    expect(items[0]!.text()).toContain('Tratei 2 erros.')
    expect(items[1]!.text()).toContain('Filmes')
    expect(w.text()).not.toContain('Já lido.')
  })

  it('agente apagado aparece só como "Agente"', async () => {
    useOrgStore(pinia).notices = [makeNotice({ id: 1, agent_id: 99 })]
    const w = await mountNotices()
    expect(w.get('[data-test="agent-notice-name"]').text()).toBe('Agente')
  })

  it.each([
    ['summary', 'check'],
    ['alert', 'triangle'],
    ['notice', 'dot'],
  ] as const)('o tipo %s tem o ícone %s', async (kind, shape) => {
    useOrgStore(pinia).notices = [makeNotice({ kind })]
    const w = await mountNotices()
    expect(w.get('[data-test="agent-notice-kind"]').attributes('data-shape')).toBe(shape)
  })

  it('o texto longo fica em até 3 linhas e abre ao clicar', async () => {
    useOrgStore(pinia).notices = [makeNotice({ text: 'x'.repeat(500) })]
    const w = await mountNotices()
    const text = w.get('[data-test="agent-notice-text"]')
    expect(text.classes()).toContain('line-clamp-3')
    expect(text.attributes('aria-expanded')).toBe('false')
    await text.trigger('click')
    expect(text.classes()).not.toContain('line-clamp-3')
    expect(text.attributes('aria-expanded')).toBe('true')
    await text.trigger('click')
    expect(text.classes()).toContain('line-clamp-3')
  })

  it('"Abrir agente" leva ao painel do agente no projeto dele', async () => {
    useOrgStore(pinia).notices = [makeNotice({ id: 1, agent_id: 1 }), makeNotice({ id: 2, agent_id: 99 })]
    const w = await mountNotices()
    const links = w.findAll('[data-test="agent-notice-open"]')
    expect(links).toHaveLength(1)
    expect(links[0]!.text()).toBe('Abrir agente')
    expect(links[0]!.attributes('href')).toBe('/agentes/3?agente=1')
  })

  it('"Marcar como lido" marca só aquele aviso pela API', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/agent-notices/read': (init) => {
        bodies.push(JSON.parse(String(init?.body)))
        return jsonResponse({ updated: 1 })
      },
    }))
    const store = useOrgStore(pinia)
    store.notices = [makeNotice({ id: 1 }), makeNotice({ id: 2, text: 'Outro.' })]
    const w = await mountNotices()
    await w.findAll('[data-test="agent-notice-read"]')[0]!.trigger('click')
    await flushPromises()
    expect(bodies).toEqual([{ ids: [1] }])
    expect(w.findAll('[data-test="agent-notice"]')).toHaveLength(1)
    expect(store.unreadCount).toBe(1)
  })

  it('"Marcar todos como lidos" manda todos os ids e a seção some', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/agent-notices/read': (init) => {
        bodies.push(JSON.parse(String(init?.body)))
        return jsonResponse({ updated: 2 })
      },
    }))
    const store = useOrgStore(pinia)
    store.notices = [makeNotice({ id: 1 }), makeNotice({ id: 2 }), makeNotice({ id: 3, read_at: 4 })]
    const w = await mountNotices()
    await w.get('[data-test="agent-notices-read-all"]').trigger('click')
    await flushPromises()
    expect(bodies).toEqual([{ ids: [1, 2] }])
    expect(w.find('[data-test="agent-notices"]').exists()).toBe(false)
  })

  it('falha da API mostra o erro e mantém o aviso', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'POST /api/agent-notices/read': () => jsonResponse({ detail: 'Deu ruim' }, 500),
    }))
    useOrgStore(pinia).notices = [makeNotice({ id: 1 })]
    const w = await mountNotices()
    await w.get('[data-test="agent-notice-read"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-test="agent-notices-error"]').text()).toContain('Deu ruim')
    expect(w.findAll('[data-test="agent-notice"]')).toHaveLength(1)
  })
})
