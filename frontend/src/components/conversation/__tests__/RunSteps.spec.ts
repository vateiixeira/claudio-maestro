import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { emptyConversation, useConversationStore } from '../../../stores/conversation'
import { jsonResponse, makeSnapshot, routeFetch } from '../../../test/factories'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: () => () => {},
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import RunSteps from '../RunSteps.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

const user = (id: string, t = id) => ({ type: 'user', id, text: t })
const text = (id: string) => ({ type: 'text', id, text: `texto ${id}`, streaming: false, parent_tool_use_id: null })
const tool = (id: string, name: string) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input: { file_path: `/p/${id}.py` },
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null,
})

const URL = 'GET /api/sessions/run1'
const snapshot = (overrides: Record<string, unknown> = {}) => makeSnapshot({ session_id: 'run1', seq: 1, ...overrides } as never)

async function mountSteps(handler: () => Response = () => jsonResponse(snapshot())) {
  vi.stubGlobal('fetch', routeFetch({ [URL]: handler }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  const w = mount(RunSteps, { props: { sessionId: 'run1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}

describe('passo a passo da execução', () => {
  it('renders the turns of the run session', async () => {
    const w = await mountSteps(() => jsonResponse(snapshot({
      items: [user('u1', 'faça a rotina'), text('a'), tool('r1', 'Read'), tool('r2', 'Read')],
    })))
    expect(w.find('[data-test="run-steps"]').exists()).toBe(true)
    expect(w.findAll('[data-test="user-message-row"]')).toHaveLength(1)
    const entries = w.findAll('[data-test="turn-entry"]')
    expect(entries).toHaveLength(2)
    expect(entries[0]!.text()).toContain('texto a')
    expect(entries[1]!.findComponent({ name: 'WorkBlock' }).exists()).toBe(true)
  })

  it('shows the pending request of the session', async () => {
    const w = await mountSteps(() => jsonResponse(snapshot({
      state: 'awaiting_decision',
      items: [user('u1'), tool('b1', 'Bash')],
      prompts: [{ prompt_id: 'p1', tool_use_id: 'tu-b1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true }],
    })))
    expect(w.find('[data-prompt-card]').exists()).toBe(true)
  })

  it('leaves the requests out when asked to', async () => {
    vi.stubGlobal('fetch', routeFetch({
      [URL]: () => jsonResponse(snapshot({
        state: 'awaiting_decision',
        items: [user('u1'), tool('b1', 'Bash')],
        prompts: [{ prompt_id: 'p1', tool_use_id: 'tu-b1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true }],
      })),
    }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    const w = mount(RunSteps, { props: { sessionId: 'run1', prompts: false }, global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(w.find('[data-test="run-steps"]').exists()).toBe(true)
    expect(w.find('[data-test="run-turn"]').exists()).toBe(true)
    expect(w.find('[data-prompt-card]').exists()).toBe(false)
  })

  it('forgets the session on unmount only when it loaded it', async () => {
    const first = await mountSteps()
    const store = useConversationStore(pinia)
    const forget = vi.spyOn(store, 'forget')
    first.unmount()
    expect(forget).toHaveBeenCalledWith('run1')

    forget.mockClear()
    store.bySession.run1 = emptyConversation('run1')
    const second = await mountSteps()
    second.unmount()
    expect(forget).not.toHaveBeenCalled()
  })

  it('shows the error and retries', async () => {
    let calls = 0
    const w = await mountSteps(() => (++calls === 1 ? jsonResponse({ detail: 'Falhou ao carregar.' }, 500) : jsonResponse(snapshot({ items: [user('u1'), text('a')] }))))
    expect(w.text()).toContain('Falhou ao carregar.')
    await w.find('[data-test="retry-load"]').trigger('click')
    await flushPromises()
    expect(calls).toBe(2)
    expect(w.find('[data-test="turn-entry"]').exists()).toBe(true)
  })

  it('shows a loading note until the snapshot arrives', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    const w = mount(RunSteps, { props: { sessionId: 'run1' }, global: { plugins: [pinia, router] } })
    expect(w.text()).toContain('Carregando…')
  })
})
