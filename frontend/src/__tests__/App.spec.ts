import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { ref } from 'vue'

vi.mock('../api/socket', () => ({ useEventSocket: () => ({ status: ref('connected') }) }))
vi.mock('../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

import App from '../App.vue'
import { createAppRouter } from '../router'
import { jsonResponse, routeFetch } from '../test/factories'

enableAutoUnmount(afterEach)
beforeEach(() => {
  setActivePinia(createPinia())
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
})
