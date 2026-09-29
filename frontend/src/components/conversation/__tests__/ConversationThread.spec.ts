import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationThread from '../ConversationThread.vue'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

function mountThread() {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationThread, { props: { id: 's1' }, global: { plugins: [pinia, router] } })
}

describe('corpo da conversa', () => {
  it('carrega a conversa e mostra o compositor', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [{ type: 'user', id: 'u1', text: 'oi' }] })),
      'POST /api/sessions/s1/seen': () => jsonResponse({}),
    }))
    const wrapper = mountThread()
    await flushPromises()

    expect(wrapper.text()).toContain('oi')
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('avisa quando a conversa não existe', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Sessão não encontrada.' }, 404) }))
    const wrapper = mountThread()
    await flushPromises()

    expect(wrapper.emitted('missing')).toHaveLength(1)
  })
})
