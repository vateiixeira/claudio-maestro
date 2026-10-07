import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { ref } from 'vue'

vi.mock('../api/socket', () => ({ useEventSocket: () => ({ status: ref('connected'), onSession: () => () => {}, onOpen: () => () => {}, onClose: () => () => {} }) }))
vi.mock('../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

import App from '../App.vue'
import AppSidebar from '../components/sidebar/AppSidebar.vue'
import { createAppRouter } from '../router'
import { useNewConversationStore } from '../stores/newConversation'
import { useSessionsStore } from '../stores/sessions'
import { jsonResponse, makeSession, routeFetch } from '../test/factories'
import { loadEverything } from '../stores/realtime'

enableAutoUnmount(afterEach)
let pinia: ReturnType<typeof createPinia>
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/layout': () => jsonResponse({}) }))
})
afterEach(() => vi.unstubAllGlobals())

describe('estrutura do app', () => {
  it('a área principal é o único scroller e ancora os elementos sr-only', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias')
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    const main = wrapper.find('main')
    // `relative` gives absolutely positioned children (sr-only) a container inside the
    // scroller; without it they enlarge the whole document and the window scrolls too.
    expect(main.classes()).toEqual(expect.arrayContaining(['relative', 'overflow-y-auto']))
  })

  it('a raiz do app recorta o que transborda, para a janela nunca rolar', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias')
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    // Em janelas baixas o menu lateral passa da altura; a raiz recorta em vez de esticar a página.
    expect(wrapper.find('main').element.parentElement!.classList).toContain('overflow-hidden')
  })

  it('o título da aba conta só as esperas que precisam de você', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'c', display_state: 'waiting', pending_kind: 'tool' }),
    ])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias')
    mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(document.title).toBe('(2) Cláudio Maestro')
  })

  it('o título da aba ignora a conversa marcada não lida', async () => {
    useSessionsStore(pinia).setForProject(1, [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: true, mark: 'on_hold' }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: true }),
    ])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias')
    mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(document.title).toBe('(1) Cláudio Maestro')
  })

  it('o atalho C numa conversa abre o modal no projeto e no agrupador dela', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', project_id: 1, group_id: 4 })])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true, cancelable: true }))
    const store = useNewConversationStore(pinia)
    expect(store.isOpen).toBe(true)
    expect(store.presetProjectId).toBe(1)
    expect(store.presetGroupId).toBe(4)
  })

  it('o atalho C numa conversa sem agrupador pede "Nenhum" (null), não "sem preferência"', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', project_id: 1, group_id: null })])
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true, cancelable: true }))
    expect(useNewConversationStore(pinia).presetGroupId).toBeNull()
  })

  it('o atalho C fora de uma conversa não indica agrupador (undefined)', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/inbox')
    mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true, cancelable: true }))
    const store = useNewConversationStore(pinia)
    expect(store.isOpen).toBe(true)
    expect(store.presetGroupId).toBeUndefined()
  })

  describe('atalho N', () => {
    function press(target: HTMLElement = document.body) {
      const event = new KeyboardEvent('keydown', { key: 'n', bubbles: true, cancelable: true })
      target.dispatchEvent(event)
      return event
    }
    async function mountAt(path: string) {
      useSessionsStore(pinia).setForProject(1, [
        makeSession({ session_id: 'cur', display_state: 'waiting', unread: true, last_activity_at: 30 }),
        makeSession({ session_id: 'next', display_state: 'waiting', unread: true, last_activity_at: 20 }),
        makeSession({ session_id: 'later', display_state: 'waiting', pending_kind: 'tool', last_activity_at: 10 }),
      ])
      const router = createAppRouter(createMemoryHistory())
      await router.push(path)
      mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body })
      await flushPromises()
      return router
    }

    it('vai para a primeira que aguarda você, de qualquer tela', async () => {
      const router = await mountAt('/preferencias')
      const event = press()
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/sessions/cur')
      expect(event.defaultPrevented).toBe(true)
    })

    it('numa conversa, pula a atual', async () => {
      const router = await mountAt('/sessions/cur')
      press()
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/sessions/next')
    })

    it.each([['cur', 'next'], ['next', 'later'], ['later', 'cur']])('numa conversa, segue a fila em ordem: %s vai para %s', async (from, to) => {
      const router = await mountAt(`/sessions/${from}`)
      press()
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe(`/sessions/${to}`)
    })

    it('na tela do projeto com conversa embutida, pula a aberta', async () => {
      const router = await mountAt('/projects/1?sessao=cur')
      press()
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/sessions/next')
    })

    it('não faz nada em campo de texto, com modificador ou sem outra conversa', async () => {
      const router = await mountAt('/preferencias')
      const input = document.createElement('input')
      document.body.appendChild(input)
      press(input)
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', ctrlKey: true, bubbles: true, cancelable: true }))
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/preferencias')
      input.remove()

      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 'only', display_state: 'waiting', unread: true })])
      await router.push('/sessions/only')
      const event = press()
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/sessions/only')
      expect(event.defaultPrevented).toBe(false)
    })
  })
})

describe('página de leitura', () => {
  it('não monta a barra lateral nem liga o tempo real', async () => {
    vi.mocked(loadEverything).mockClear()
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1/markdown?path=docs%2Fa.md': () => jsonResponse({ path: '/p/docs/a.md', content: '# A', mtime: 1 }),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1/ver?caminho=docs%2Fa.md')
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(wrapper.findComponent(AppSidebar).exists()).toBe(false)
    expect(wrapper.find('main').exists()).toBe(false)
    expect(loadEverything).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="md-body"] h1').text()).toBe('A')
    expect(document.title).toBe('A · Cláudio Maestro')
  })
})
