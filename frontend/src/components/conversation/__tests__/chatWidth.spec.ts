import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import ConversationBlock from '../ConversationBlock.vue'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: () => () => {},
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import ConversationThread from '../ConversationThread.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

const user = (id: string, text: string) => ({ type: 'user', id, text, images: [] })
const reply = (id: string) => ({ type: 'text', id, text: 'ok', streaming: false, parent_tool_use_id: null })

describe('largura da coluna do chat', () => {
  it('cabeçalho de turnos, corpo e compositor usam a variável de largura', async () => {
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({
        state: 'idle',
        seq: 4,
        items: [user('u1', 'primeira'), reply('a1'), user('u2', 'segunda'), reply('a2')] as never,
      })),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
    await flushPromises()
    for (const test of ['chat-bar-column', 'chat-body-column', 'chat-composer-column']) {
      const column = w.find(`[data-test="${test}"]`)
      expect(column.exists(), test).toBe(true)
      expect(column.classes(), test).toContain('max-w-(--chat-width)')
      expect(column.classes().some((c) => c.startsWith('max-w-[') && c.includes('px')), test).toBe(false)
      expect(column.classes(), test).toEqual(expect.arrayContaining(['mx-auto', 'w-full', 'px-4']))
    }
  })

  it('texto do assistente e mensagem do usuário têm largura de leitura própria', () => {
    const text = mount(ConversationBlock, { props: { item: { type: 'text', id: 'x', text: 'oi', streaming: false, parent_tool_use_id: null } } })
    expect(text.find('.markdown').classes()).toContain('max-w-[90ch]')
    const userMsg = mount(ConversationBlock, { props: { item: { type: 'user', id: 'u', text: 'oi', images: [] } } })
    expect(userMsg.find('[data-test="user-message-card"]').classes()).toContain('max-w-[72ch]')
  })
})
