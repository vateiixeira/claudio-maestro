import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import type { ToolItem } from '../../types/conversation'
import { useChangesPanelStore } from '../../stores/changesPanel'
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
})
