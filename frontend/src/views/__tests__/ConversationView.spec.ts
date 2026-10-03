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
import { useGroupsStore } from '../../stores/groups'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { jsonResponse, makeGroup, makeProject, makeSession, makeSnapshot, routeFetch } from '../../test/factories'

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
  'GET /api/sessions/s1/digest': () => jsonResponse(null),
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
  it('o progresso do plano fica no painel Detalhes, não acima da conversa', async () => {
    const plan = { path: '/home/vi/dev/loja-online/docs/plan.md', title: 'Plano da loja', total: 12, done: 3, current: { number: 4, title: 'Faixa do plano' } }
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'running', plan })])
    const { wrapper } = await mountAt('/sessions/s1', {
      'GET /api/sessions/s1/plan': () => jsonResponse({ link: 'auto', path: plan.path, plan, tasks: [] }),
    })
    expect(wrapper.findAll('[data-test="plan-strip"]')).toHaveLength(1)
    const inPanel = wrapper.find('[data-test="details-panel"] [data-test="plan-strip"]')
    expect(inPanel.exists()).toBe(true)
    expect(inPanel.text()).toContain('Plano da loja')
    expect(inPanel.text()).toContain('4 de 12')
    expect(inPanel.find('[data-status="current"]').text()).toContain('Faixa do plano')
  })

  it('não mostra o progresso do plano sem plano', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="plan-strip"]').exists()).toBe(false)
  })

  it('mostra trilha, título e o painel Detalhes aberto por padrão', async () => {
    const { wrapper } = await mountAt('/sessions/s1')

    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('Conversas')
    expect(wrapper.find('[data-test="breadcrumb"]').text()).toContain('loja-online')
    // Every crumb shares the sans style: no mono / uppercase on the root.
    const root = wrapper.find('[data-test="breadcrumb"] a')
    expect(root.text()).toBe('Conversas')
    expect(root.classes()).not.toContain('font-mono')
    expect(root.classes()).not.toContain('uppercase')
    expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
  })

  it('caminho e título ficam numa só faixa, com as ações à direita', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.findAll('[data-test="breadcrumb"]')).toHaveLength(1)
    const strip = wrapper.get('[data-test="header-strip"]')
    expect(strip.find('[data-test="breadcrumb"]').exists()).toBe(true)
    expect(strip.find('[data-test="conversation-title"]').exists()).toBe(true)
    expect(strip.find('[data-test="toggle-finished"]').exists()).toBe(true)
    expect(strip.find('[data-test="header-menu"]').exists()).toBe(true)
    expect(strip.find('[data-test="toggle-details"]').exists()).toBe(true)
  })

  it('o botão de Detalhes tem nome e title, e um ícone SVG', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    const toggle = wrapper.get('[data-test="toggle-details"]')
    expect(toggle.attributes('aria-label')).toBe('Mostrar ou esconder detalhes')
    expect(toggle.attributes('title')).toBe('Mostrar ou esconder detalhes')
    expect(toggle.find('svg[aria-hidden="true"]').exists()).toBe(true)
  })

  it('projeto, agrupador e branch só aparecem abaixo da faixa com o painel fechado', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting', group_id: 2 })])
    useGroupsStore(pinia).groups = [makeGroup({ id: 2, name: 'Checkout' })]
    const { wrapper } = await mountAt('/sessions/s1')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="header-meta"]').exists()).toBe(false)

    await wrapper.get('[data-test="toggle-details"]').trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="header-meta"] [data-test="header-group"]').text()).toContain('Checkout')
  })

  it('esconde o painel e lembra a escolha', async () => {
    const { wrapper } = await mountAt('/sessions/s1')
    await wrapper.find('[data-test="toggle-details"]').trigger('click')

    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    expect(localStorage.getItem('maestro:details-open')).toBe('false')
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

  it('o menu ⋯ não tem Renomear; clicar no título abre a edição', async () => {
    const { wrapper } = await mountAt('/sessions/s1')

    await wrapper.find('[data-test="header-menu"]').trigger('click')
    expect(wrapper.find('[data-test="menu-rename"]').exists()).toBe(false)
    expect(wrapper.findAll('[role="menuitem"]').map((b) => b.text())).toEqual(['Abrir projeto no editor', 'Copiar ID da sessão'])
    await wrapper.find('[data-test="conversation-title"]').trigger('click')
    expect(wrapper.find('[data-test="title-input"]').exists()).toBe(true)
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
    localStorage.setItem('maestro:details-open', 'false')
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
    localStorage.setItem('maestro:details-open', 'false')
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
      'GET /api/sessions/s2/digest': () => jsonResponse(null),
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

    it('fechar pelo X da gaveta devolve o foco ao botão Detalhes, como o Esc', async () => {
      const wrapper = await mountNarrow()
      const toggle = wrapper.find('[data-test="toggle-details"]')
      await toggle.trigger('click')
      await flushPromises()
      await wrapper.get('[data-test="details-drawer"] [aria-label="Fechar detalhes"]').trigger('click')
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
      expect(live().text()).toBe('Sua vez')

      const sessions = useSessionsStore(pinia)
      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'running', state: 'running' })])
      await flushPromises()
      expect(live().text()).toBe('Em execução')

      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting', state: 'awaiting_decision', awaiting_decision: true })])
      await flushPromises()
      expect(live().text()).toBe('Aguardando você')

      sessions.setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', display_state: 'waiting', state: 'error' })])
      await flushPromises()
      expect(live().text()).toBe('Erro')
    })
  })

  describe('embutida na tela do projeto', () => {
    async function mountEmbedded(handlers = {}, props: Record<string, unknown> = {}) {
      vi.stubGlobal('fetch', routeFetch({ ...baseFetch, ...handlers }))
      const router = createAppRouter(createMemoryHistory())
      await router.push('/projects/1?sessao=s1')
      const wrapper = mount(ConversationView, { props: { id: 's1', embedded: true, ...props }, global: { plugins: [pinia, router] } })
      await flushPromises()
      return wrapper
    }

    it('troca a trilha por uma barra compacta com título, Detalhes, Tela cheia e Fechar', async () => {
      const wrapper = await mountEmbedded()

      expect(wrapper.find('[data-test="breadcrumb"]').exists()).toBe(false)
      expect(wrapper.get('[data-test="embedded-bar"] [data-test="embedded-title"]').text()).toBe('Corrigir login')
      expect(wrapper.find('[data-test="embedded-bar"] [data-test="toggle-details"]').exists()).toBe(true)
      const full = wrapper.get('[data-test="embedded-fullscreen"]')
      expect(full.attributes('href')).toBe('/sessions/s1')
      expect(full.attributes('aria-label')).toBe('Abrir em tela cheia')
      expect(full.attributes('title')).toBe('Abrir em tela cheia')
      const close = wrapper.get('[data-test="embedded-close"]')
      expect(close.attributes('href')).toBe('/projects/1')
      expect(close.attributes('aria-label')).toBe('Fechar conversa')
      expect(close.attributes('title')).toBe('Fechar conversa')
    })

    it('o painel Detalhes é sempre gaveta, mesmo em tela larga e com a preferência aberta', async () => {
      const wrapper = await mountEmbedded()

      expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
      await wrapper.get('[data-test="toggle-details"]').trigger('click')
      expect(wrapper.find('[data-test="details-drawer"] [data-test="details-panel"]').exists()).toBe(true)
      expect(localStorage.getItem('maestro:details-open')).toBeNull()
      await wrapper.get('[data-test="toggle-details"]').trigger('click')
      expect(wrapper.find('[data-test="details-drawer"]').exists()).toBe(false)
    })

    it('mantém cabeçalho e fio da conversa', async () => {
      const wrapper = await mountEmbedded()

      expect(wrapper.find('[data-test="conversation-title"]').text()).toBe('Corrigir login')
    })

    it('conversa inexistente mostra o aviso e mantém Fechar, usando o projeto recebido', async () => {
      const wrapper = await mountEmbedded(
        { 'GET /api/sessions/s9': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) },
        { id: 's9', projectId: 1 },
      )

      expect(wrapper.find('[data-test="conversation-missing"]').exists()).toBe(true)
      expect(wrapper.get('[data-test="embedded-close"]').attributes('href')).toBe('/projects/1')
    })

    it('Fechar volta ao projeto aberto, mesmo que a sessão seja de outro projeto', async () => {
      const wrapper = await mountEmbedded({}, { projectId: 2 })

      expect(wrapper.get('[data-test="embedded-close"]').attributes('href')).toBe('/projects/2')
    })

    it('a gaveta de Detalhes não passa da largura da coluna, nem alargada', async () => {
      const wrapper = await mountEmbedded()
      await wrapper.get('[data-test="toggle-details"]').trigger('click')

      expect(wrapper.get('[data-test="details-drawer"]').classes()).toContain('max-w-full')
      expect(wrapper.get('[data-test="details-panel"]').classes()).toContain('max-w-full')
    })

    it('sem embedded continua com a trilha e sem a barra compacta', async () => {
      const { wrapper } = await mountAt('/sessions/s1')

      expect(wrapper.find('[data-test="embedded-bar"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="breadcrumb"]').exists()).toBe(true)
    })
  })
})

describe('resumo ao voltar', () => {
  const NOW = Math.floor(Date.now() / 1000)
  const SEEN = NOW - 42 * 60
  const item = (type: string, id: string, at: number, extra: Record<string, unknown> = {}) =>
    ({ type, id, tool_use_id: id, name: 'Bash', input: {}, result: null, streaming: false, parent_tool_use_id: null, text: id, at, ...extra })
  const ITEMS = [
    item('user', 'u1', SEEN - 600),
    item('tool', 't1', SEEN - 590),
    item('user', 'u2', SEEN + 60),
    item('tool', 't2', SEEN + 120, { name: 'Edit', input: { file_path: '/p/a.py' } }),
    item('tool', 't3', SEEN + 180),
  ]
  let digestPosts: number
  let seenPosts: number

  function stubSession(overrides: Parameters<typeof makeSession>[0] = {}) {
    useSessionsStore(pinia).setForProject(1, [makeSession({
      session_id: 's1', title: 'Corrigir login', display_state: 'waiting',
      last_seen_at: SEEN, last_activity_at: NOW - 60, ...overrides,
    })])
  }
  async function mountAway(items = ITEMS) {
    digestPosts = 0
    seenPosts = 0
    return mountAt('/sessions/s1', {
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ title: 'Corrigir login', items: items as never, last_seen_at: SEEN, last_activity_at: NOW - 60 })),
      'GET /api/digest/config': () => jsonResponse({ config: {}, status: { enabled: false, running: false, next_run_at: null, paused_until: null } }),
      'POST /api/sessions/s1/digest': () => { digestPosts++; return jsonResponse({ queued: true }, 202) },
      'POST /api/sessions/s1/seen': () => { seenPosts++; return jsonResponse(makeSession()) },
    })
  }

  it('aparece no topo com o tempo e as contagens desde a última vez que viu', async () => {
    stubSession()
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="away-title"]').text()).toBe('Enquanto você estava fora · há 42 min')
    expect(wrapper.find('[data-test="away-counts"]').text()).toBe('1 turno · 2 ações · 1 arquivo alterado')
    // Above the thread, not inside its scroller.
    expect(wrapper.find('[data-test="conversation-scroller"] [data-test="away-summary"]').exists()).toBe(false)
  })

  it('guarda o valor antigo: marcar como vista não muda o card', async () => {
    stubSession()
    vi.useFakeTimers({ toFake: ['setTimeout'] })
    try {
      const { wrapper } = await mountAway()
      await vi.advanceTimersByTimeAsync(400)
      await flushPromises()
      expect(seenPosts).toBeGreaterThan(0)
      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', last_seen_at: NOW, last_activity_at: NOW - 60 })])
      await flushPromises()
      expect(wrapper.find('[data-test="away-title"]').text()).toBe('Enquanto você estava fora · há 42 min')
      expect(wrapper.find('[data-test="away-counts"]').text()).toBe('1 turno · 2 ações · 1 arquivo alterado')
    } finally {
      vi.useRealTimers()
    }
  })

  it('na carga a frio a lista de sessões chega depois de marcar como vista e o card aparece', async () => {
    useSessionsStore(pinia).setForProject(1, [])
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="away-title"]').text()).toBe('Enquanto você estava fora · há 42 min')
    // The list loads after the thread told the backend it was seen: it already carries the new moment.
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Corrigir login', last_seen_at: NOW, last_activity_at: NOW - 60 })])
    await flushPromises()
    expect(wrapper.find('[data-test="away-title"]').text()).toBe('Enquanto você estava fora · há 42 min')
    expect(wrapper.find('[data-test="away-counts"]').text()).toBe('1 turno · 2 ações · 1 arquivo alterado')
  })

  it('não aparece com menos de 15 minutos', async () => {
    stubSession({ last_seen_at: NOW - 10 * 60 })
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="away-summary"]').exists()).toBe(false)
  })

  it('não aparece sem atividade depois de ter visto', async () => {
    stubSession({ last_activity_at: SEEN - 5 })
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="away-summary"]').exists()).toBe(false)
  })

  it('não aparece em conversa nunca vista', async () => {
    stubSession({ last_seen_at: null })
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="away-summary"]').exists()).toBe(false)
  })

  it('o × fecha o card', async () => {
    stubSession()
    const { wrapper } = await mountAway()
    await wrapper.get('[data-test="away-close"]').trigger('click')
    expect(wrapper.find('[data-test="away-summary"]').exists()).toBe(false)
  })

  it('com o resumo desligado só roda o modelo ao clicar em "Resumir agora"', async () => {
    stubSession()
    const { wrapper } = await mountAway()
    expect(digestPosts).toBe(0)
    expect(wrapper.find('[data-test="away-done"]').exists()).toBe(false)
    await wrapper.get('[data-test="away-digest-request"]').trigger('click')
    await flushPromises()
    expect(digestPosts).toBe(1)
  })

  it('"Ver alterações" abre o painel de Detalhes que estava fechado', async () => {
    localStorage.setItem('maestro:details-open', 'false')
    stubSession()
    const { wrapper } = await mountAway()
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(false)
    await wrapper.get('[data-test="away-view-changes"]').trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').exists()).toBe(true)
    expect(localStorage.getItem('maestro:details-open')).toBe('false')
  })

  it('"Ir para o fim" rola a conversa até o fim', async () => {
    stubSession()
    const scrollTo = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo })
    try {
      const { wrapper } = await mountAway()
      const scroller = wrapper.get('[data-test="conversation-scroller"]')
      Object.defineProperty(scroller.element, 'scrollHeight', { configurable: true, value: 2000 })
      await wrapper.get('[data-test="away-jump"]').trigger('click')
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 2000 }))
    } finally {
      delete (HTMLElement.prototype as unknown as Record<string, unknown>).scrollTo
    }
  })
})
