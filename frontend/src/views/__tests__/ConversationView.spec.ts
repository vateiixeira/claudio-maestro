import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import type { ToolItem } from '../../types/conversation'
import { useChangesPanelStore } from '../../stores/changesPanel'
const fake = vi.hoisted(() => ({ reconnect: new Set<() => void>() }))
vi.mock('../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: () => () => {},
    onReconnect: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
    onOpen: (h: () => void) => { fake.reconnect.add(h); return () => fake.reconnect.delete(h) },
  }),
}))

import ConversationView from '../ConversationView.vue'
import { createAppRouter } from '../../router'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeProject, makeSession, makeSnapshot, routeFetch } from '../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

function stubMedia(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: wide, media: query, addEventListener() {}, removeEventListener() {},
  }))
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting' })])
  fake.reconnect.clear()
  localStorage.clear()
  stubMedia(true)
})
afterEach(() => vi.unstubAllGlobals())

const baseFetch = {
  'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Corrigir login' })),
  'GET /api/sessions/s1/changes': () => jsonResponse({ repos: [] }),
  'POST /api/sessions/s1/seen': () => jsonResponse(makeSession()),
  'GET /api/projects/1/git': () => jsonResponse({ repos: [] }),
  'GET /api/models': () => jsonResponse([]),
}

async function mountAt(path: string, handlers = {}) {
  vi.stubGlobal('fetch', routeFetch({ ...baseFetch, ...handlers }))
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('página da conversa', () => {
  it('mostra trilha, título e o painel Detalhes aberto por padrão', async () => {
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('Conversas')
    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
  })

  it('abrir a página grava a conversa entre as abertas recentemente', async () => {
    await mountAt('/sessions/s1')
    expect(JSON.parse(localStorage.getItem('vibing:recent-conversations')!)).toEqual(['s1'])
  })

  it('trocar de conversa grava a nova id', async () => {
    const { wrapper } = await mountAt('/sessions/s1', {
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', title: 'Outra' })),
      'POST /api/sessions/s2/seen': () => jsonResponse(makeSession({ session_id: 's2' })),
    })
    await wrapper.setProps({ id: 's2' })
    await flushPromises()
    expect(JSON.parse(localStorage.getItem('vibing:recent-conversations')!)).toEqual(['s2', 's1'])
  })

  it('esconde o painel e lembra a escolha', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    await wrapper.find('[data-test="toggle-details"]').trigger('click')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    expect(localStorage.getItem('vibing:details-open')).toBe('false')
  })

  it('funciona sem localStorage', async () => {
    vi.stubGlobal('localStorage', {
      getItem() { throw new Error('bloqueado') },
      setItem() { throw new Error('bloqueado') },
      clear() {},
    })
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
    await wrapper.find('[data-test="toggle-details"]').trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
  })

  it('em tela estreita o painel vira gaveta fechada', async () => {
    stubMedia(false)
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    await wrapper.find('[data-test="toggle-details"]').trigger('click')
    expect(wrapper.find('[data-test="details-drawer"] [data-test="details-panel"]').exists()).toBe(true)
  })

  it('renomeia pelo título', async () => {
    const fetch = routeFetch({
      ...baseFetch,
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ session_id: 's1', title: 'Novo nome' })),
    })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    await wrapper.find('[data-test="title-input"]').setValue('Novo nome')
    await wrapper.find('[data-test="title-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    const patch = fetch.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ title: 'Novo nome' })
  })

  it('mostra "Conversa não encontrada" para id desconhecido', async () => {
    const { wrapper } = await mountAt('/sessions/s1', {
      'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404),
    })

    expect(wrapper.find('[data-test="conversation-missing"]').text()).toContain('Conversa não encontrada')
    expect(wrapper.find('[data-test="conversation-missing"] a').attributes('href')).toBe('/sessions')
  })

  it('copia o id da sessão pelo menu', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { wrapper } = await mountAt('/sessions/s1')

    await wrapper.find('[data-test="header-menu"]').trigger('click')
    await wrapper.find('[data-test="menu-copy-id"]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('s1')
  })
  const editItem: ToolItem = {
    type: 'tool', id: 'e1', tool_use_id: 'e1', name: 'Edit', input: { file_path: '/p/a.ts' },
    result: null, streaming: false, parent_tool_use_id: null,
  }

  it('Esc cancela a renomeação sem enviar nada', async () => {
    const fetch = routeFetch(baseFetch)
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    await wrapper.find('[data-test="title-input"]').setValue('Outro nome')
    await wrapper.find('[data-test="title-input"]').trigger('keydown', { key: 'Escape' })

    expect(wrapper.find('[data-test="title-input"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Corrigir login')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  })

  it('rejeita título vazio sem enviar', async () => {
    const fetch = routeFetch(baseFetch)
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    await wrapper.find('[data-test="title-input"]').setValue('   ')
    await wrapper.find('[data-test="title-input"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(wrapper.find('[data-test="header-error"]').text()).toBe('O título não pode ficar vazio.')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  })

  it('Finalizar envia finished: true', async () => {
    const fetch = routeFetch({
      ...baseFetch,
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ session_id: 's1', display_state: 'finished' })),
    })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.find('[data-test="toggle-finished"]').text()).toBe('Finalizar')
    await wrapper.find('[data-test="toggle-finished"]').trigger('click')
    await flushPromises()

    const patch = fetch.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ finished: true })
    expect(wrapper.find('[data-test="toggle-finished"]').text()).toBe('Reabrir')
  })

  it('"Ver alterações" abre o painel lateral quando estava fechado', async () => {
    localStorage.setItem('vibing:details-open', 'false')
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)

    useChangesPanelStore(pinia).open('s1', editItem)
    await flushPromises()

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
  })

  it('"Ver alterações" abre a gaveta em tela estreita', async () => {
    stubMedia(false)
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(false)

    useChangesPanelStore(pinia).open('s1', editItem)
    await flushPromises()

    expect(wrapper.find('[data-test="details-drawer"] [data-test="details-panel"]').exists()).toBe(true)
  })

  it('uma edição já aberta ao montar abre o painel', async () => {
    localStorage.setItem('vibing:details-open', 'false')
    useChangesPanelStore(pinia).open('s1', editItem)
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
  })

  it('Esc fecha o menu "⋯" e devolve o foco ao botão', async () => {
    vi.stubGlobal('fetch', routeFetch(baseFetch))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, attachTo: document.body, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="header-menu"]').trigger('click')
    expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()

    expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('[data-test="header-menu"]').element)
  })

  it('clicar fora fecha o menu "⋯", clicar dentro não', async () => {
    const { wrapper } = await mountAt('/sessions/s1')

    await wrapper.find('[data-test="header-menu"]').trigger('click')
    wrapper.find('[data-test="menu-copy-id"]').element.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(true)

    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(false)
  })

  describe('aviso de atividade externa', () => {
    const external = (value: boolean) => makeSnapshot({ external_activity: value } as never)

    it('avisa atividade externa vinda do retrato', async () => {
      const { wrapper } = await mountAt('/sessions/s1', { 'GET /api/sessions/s1': () => jsonResponse(external(true)) })
      expect(wrapper.find('[data-test="external-activity"]').text()).toContain('Esta sessão foi modificada fora do app no último minuto.')
    })

    it('avisa atividade externa vinda do envio', async () => {
      const { wrapper } = await mountAt('/sessions/s1', {
        'POST /api/sessions/s1/messages': () => jsonResponse({ state: 'connecting', external_activity: true }),
      })
      expect(wrapper.find('[data-test="external-activity"]').exists()).toBe(false)
      await wrapper.find('textarea').setValue('oi')
      await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(wrapper.find('[data-test="external-activity"]').text()).toContain('pode embaralhar o histórico')
    })

    it('retrato posterior com external_activity false limpa o aviso', async () => {
      let active = true
      const { wrapper } = await mountAt('/sessions/s1', { 'GET /api/sessions/s1': () => jsonResponse(external(active)) })
      expect(wrapper.find('[data-test="external-activity"]').exists()).toBe(true)
      active = false
      fake.reconnect.forEach((h) => h())
      await flushPromises()
      expect(wrapper.find('[data-test="external-activity"]').exists()).toBe(false)
    })

    it('o aviso some depois de 60 s', async () => {
      vi.useFakeTimers()
      try {
        const { wrapper } = await mountAt('/sessions/s1', { 'GET /api/sessions/s1': () => jsonResponse(external(true)) })
        expect(wrapper.find('[data-test="external-activity"]').attributes('role')).toBe('status')
        await vi.advanceTimersByTimeAsync(59_000)
        expect(wrapper.find('[data-test="external-activity"]').exists()).toBe(true)
        await vi.advanceTimersByTimeAsync(2_000)
        expect(wrapper.find('[data-test="external-activity"]').exists()).toBe(false)
      } finally {
        vi.useRealTimers()
      }
    })
  })

  it('ao trocar de conversa, a renomeação em curso de uma não vaza para a outra', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting' }),
      makeSession({ session_id: 's2', title: 'Outra conversa', display_state: 'waiting' }),
    ])
    const fetch = routeFetch({
      ...baseFetch,
      'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', title: 'Outra conversa' })),
      'GET /api/sessions/s2/changes': () => jsonResponse({ repos: [] }),
      'POST /api/sessions/s2/seen': () => jsonResponse(makeSession()),
    })
    vi.stubGlobal('fetch', fetch)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const wrapper = mount(ConversationView, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
    await flushPromises()

    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    await wrapper.find('[data-test="title-input"]').setValue('Nome novo da A')
    await wrapper.setProps({ id: 's2' })
    await flushPromises()

    expect(wrapper.find('[data-test="title-input"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Outra conversa')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  })

  describe('gaveta em tela estreita', () => {
    async function mountNarrow() {
      stubMedia(false)
      vi.stubGlobal('fetch', routeFetch(baseFetch))
      const router = createAppRouter(createMemoryHistory())
      await router.push('/sessions/s1')
      const wrapper = mount(ConversationView, { props: { id: 's1' }, attachTo: document.body, global: { plugins: [pinia, router] } })
      await flushPromises()
      return wrapper
    }

    it('ao abrir, o foco vai para dentro do painel', async () => {
      const wrapper = await mountNarrow()
      await wrapper.find('[data-test="toggle-details"]').trigger('click')
      await flushPromises()

      const drawer = wrapper.find('[data-test="details-drawer"]').element
      expect(drawer.contains(document.activeElement)).toBe(true)
    })

    it('Esc fecha a gaveta e devolve o foco ao botão que a abriu', async () => {
      const wrapper = await mountNarrow()
      const toggle = wrapper.find('[data-test="toggle-details"]')
      await toggle.trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(true)

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flushPromises()

      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(false)
      expect(document.activeElement).toBe(toggle.element)
    })

    it('Esc com o menu "⋯" aberto fecha só o menu, e o Esc seguinte fecha a gaveta', async () => {
      const wrapper = await mountNarrow()
      await wrapper.find('[data-test="toggle-details"]').trigger('click')
      await flushPromises()
      await wrapper.find('[data-test="header-menu"]').trigger('click')
      expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(true)

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()
      expect(wrapper.find('[data-test="menu-copy-id"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(true)

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(false)
    })

    it('Esc ao renomear cancela só a renomeação, e a gaveta continua', async () => {
      const wrapper = await mountNarrow()
      await wrapper.find('[data-test="toggle-details"]').trigger('click')
      await flushPromises()
      await wrapper.find('[data-test="conversation-title"]').trigger('click')
      const input = wrapper.find('[data-test="title-input"]')
      expect(input.exists()).toBe(true)

      input.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()

      expect(wrapper.find('[data-test="title-input"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(true)
    })

    it('Esc tratado por outra camada (modal, busca, menus de opção) não fecha a gaveta', async () => {
      const wrapper = await mountNarrow()
      await wrapper.find('[data-test="toggle-details"]').trigger('click')
      await flushPromises()
      const layer = document.createElement('div')
      layer.addEventListener('keydown', (e) => { if (e.key === 'Escape') e.preventDefault() })
      document.body.appendChild(layer)

      layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await flushPromises()
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(true)
      layer.remove()
    })

    it('Esc sem a gaveta aberta não faz nada', async () => {
      const wrapper = await mountNarrow()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flushPromises()
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(false)
    })
  })

  describe('anúncio do estado', () => {
    it('avisa o estado em uma região viva discreta e acompanha as mudanças', async () => {
      const { wrapper } = await mountAt('/sessions/s1')
      const live = () => wrapper.find('[data-test="state-live"]')
      expect(live().attributes('role')).toBe('status')
      expect(live().attributes('aria-live')).toBe('polite')
      expect(live().classes()).toContain('sr-only')
      expect(live().text()).toBe('Aguardando você')

      const sessions = useSessionsStore(pinia)
      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'running', state: 'running' })])
      await flushPromises()
      expect(live().text()).toBe('Em execução')

      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting', state: 'awaiting_decision', awaiting_decision: true })])
      await flushPromises()
      expect(live().text()).toBe('Pede sua decisão')

      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting', state: 'error' })])
      await flushPromises()
      expect(live().text()).toBe('Erro')
    })
  })
})
