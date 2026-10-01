import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { ref } from 'vue'

vi.mock('../api/socket', () => ({ useEventSocket: () => ({ status: ref('connected'), onSession: () => () => {}, onOpen: () => () => {}, onClose: () => () => {} }) }))
vi.mock('../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

import App from '../App.vue'
import { createAppRouter } from '../router'
import { useNewConversationStore } from '../stores/newConversation'
import { useSessionsStore } from '../stores/sessions'
import { jsonResponse, makeSession, routeFetch } from '../test/factories'

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
    expect(document.title).toBe('(2) Vini7 Vibing')
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
})
