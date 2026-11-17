import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { emptyConversation, useConversationStore } from '../../../stores/conversation'
import { jsonResponse, makeRun, routeFetch } from '../../../test/factories'
import type { Run } from '../../../types/org'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: () => () => {},
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import RunEntry from '../RunEntry.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
let store: ReturnType<typeof useConversationStore>
let load: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  store = useConversationStore(pinia)
  load = vi.spyOn(store, 'load').mockImplementation(async (id: string) => {
    store.bySession[id] = emptyConversation(id)
    return store.bySession[id]!
  })
})
afterEach(() => vi.unstubAllGlobals())

async function mountEntry(run: Run, routineName?: string | null) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  const w = mount(RunEntry, { props: { run, routineName }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { w, router }
}

describe('entrada de uma execução', () => {
  it('shows the result of a concluded run as the agent\'s text', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'concluded', ended_at: 1_790_000_060, summary: 'Linha 1\n\n- item' }))
    const result = w.find('[data-test="run-entry-result"]')
    expect(result.find('p').text()).toBe('Linha 1')
    expect(result.findAll('li')).toHaveLength(1)
  })

  it('shows html in the summary as text', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'concluded', ended_at: 1_790_000_060, summary: '<script>alert(1)</script>' }))
    const result = w.find('[data-test="run-entry-result"]')
    expect(result.find('script').exists()).toBe(false)
    expect(result.text()).toContain('<script>alert(1)</script>')
  })

  it('shows only the marker and the reason of a missed run', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'missed', session_id: null, ended_at: 1_790_000_000, reason: 'O horário passou.' }))
    expect(w.find('[data-test="run-entry-reason"]').text()).toBe('O horário passou.')
    expect(w.find('[data-test="run-entry-steps-toggle"]').exists()).toBe(false)
    expect(w.find('[data-test="run-entry-open"]').exists()).toBe(false)
    expect(w.find('[data-test="run-entry-result"]').exists()).toBe(false)
  })

  it('shows the result without steps when the session is gone', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'concluded', session_id: null, ended_at: 1_790_000_060, summary: 'ok' }))
    expect(w.find('[data-test="run-entry-result"]').text()).toContain('ok')
    expect(w.find('[data-test="run-entry-steps-toggle"]').exists()).toBe(false)
    expect(w.find('[data-test="run-entry-open"]').exists()).toBe(false)
  })

  it('treats a missing summary as none', async () => {
    const run = makeRun({ outcome: 'concluded', ended_at: 1_790_000_060 }) as Partial<Run>
    delete run.summary
    const { w } = await mountEntry(run as Run)
    expect(w.find('[data-test="run-entry-result"]').exists()).toBe(false)
  })

  it('names the marker by routine, task and source', async () => {
    const routine = await mountEntry(makeRun({ source: 'routine', routine_id: 3, outcome: 'concluded', ended_at: 1_790_000_065 }), 'Resumo diário')
    const marker = routine.w.find('[data-test="run-entry-marker"]')
    expect(marker.text()).toContain('Rotina "Resumo diário"')
    expect(marker.text()).toContain('Concluída')
    expect(marker.text()).toContain('1 min 5 s')

    const task = await mountEntry(makeRun({ source: 'assignment', task_id: 12, outcome: 'concluded', ended_at: 1_790_000_065 }))
    expect(task.w.find('[data-test="run-entry-marker"]').text()).toContain('Tarefa')
    expect(task.w.find('[data-test="run-entry-marker"] a').attributes('href')).toBe('/tarefas/12')
    expect(task.w.find('[data-test="run-entry-marker"] a').text()).toBe('#12')
  })

  it('says what a run in flight and a waiting run are', async () => {
    const running = await mountEntry(makeRun({ outcome: 'running' }))
    expect(running.w.find('[data-test="run-entry-marker"]').text()).toContain('Rodando agora')
    const waiting = await mountEntry(makeRun({ outcome: 'waiting', session_id: null }))
    expect(waiting.w.find('[data-test="run-entry-marker"]').text()).toContain('Aguardando você')
  })

  it('opens the steps in place', async () => {
    const { w, router } = await mountEntry(makeRun({ outcome: 'concluded', ended_at: 1_790_000_060, summary: 'ok' }))
    const path = router.currentRoute.value.fullPath
    const toggle = w.find('[data-test="run-entry-steps-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-test="run-steps"]').exists()).toBe(false)
    await toggle.trigger('click')
    await flushPromises()
    expect(w.find('[data-test="run-steps"]').exists()).toBe(true)
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(router.currentRoute.value.fullPath).toBe(path)
    await toggle.trigger('click')
    expect(w.find('[data-test="run-steps"]').exists()).toBe(false)
  })

  it('links to the session to open it alone', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'concluded', session_id: 'abc', ended_at: 1_790_000_060 }))
    expect(w.find('[data-test="run-entry-open"]').attributes('href')).toBe('/sessions/abc')
  })

  it('marks the root for the timeline to find', async () => {
    const { w } = await mountEntry(makeRun({ id: 7, session_id: 'abc', outcome: 'concluded', ended_at: 1_790_000_060 }))
    const root = w.find('[data-test="run-entry"]')
    expect(root.attributes('data-run-id')).toBe('7')
    expect(root.attributes('data-run-session')).toBe('abc')
    expect(root.attributes('tabindex')).toBe('-1')
  })

  it('loads the session and shows the live line while the run is in flight', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'running', session_id: 'run1', summary: 'ainda não' }))
    expect(load).toHaveBeenCalledWith('run1')
    expect(w.find('[data-test="run-entry-live"]').exists()).toBe(true)
    expect(w.find('[data-test="run-entry-cancel"]').exists()).toBe(true)
    expect(w.find('[data-test="run-entry-result"]').exists()).toBe(false)
    expect(w.find('[data-test="run-entry-reason"]').exists()).toBe(false)
  })

  it('shows the pending request of the run in flight', async () => {
    store.bySession.run1 = {
      ...emptyConversation('run1'),
      state: 'awaiting_decision',
      items: [{ type: 'tool', id: 'b1', tool_use_id: 'tu-b1', name: 'Bash', input: { command: 'ls' }, result: null, streaming: true, parent_tool_use_id: null } as never],
      prompts: [{ prompt_id: 'p1', tool_use_id: 'tu-b1', tool_name: 'Bash', input: { command: 'ls' }, can_always: true } as never],
    }
    load.mockImplementation(async (id: string) => store.bySession[id]!)
    const { w } = await mountEntry(makeRun({ outcome: 'waiting', session_id: 'run1' }))
    expect(w.find('[data-prompt-card]').exists()).toBe(true)
    expect(w.find('[data-test="run-entry-live"]').text()).toContain('esperando você')
  })

  it('swaps the live line for the result when the run ends', async () => {
    const { w } = await mountEntry(makeRun({ outcome: 'running', session_id: 'run1' }))
    await w.setProps({ run: makeRun({ outcome: 'concluded', session_id: 'run1', ended_at: 1_790_000_060, summary: 'Pronto.' }) })
    await flushPromises()
    expect(w.find('[data-test="run-entry-result"]').text()).toContain('Pronto.')
    expect(w.find('[data-test="run-entry-live"]').exists()).toBe(false)
    expect(w.find('[data-test="run-entry-cancel"]').exists()).toBe(false)
  })

  it('cancels the run and shows a failure', async () => {
    const cancel = vi.fn(() => jsonResponse({ detail: 'Não deu para cancelar.' }, 500))
    vi.stubGlobal('fetch', routeFetch({ 'POST /api/agents/1/runs/5/cancel': cancel }))
    const { w } = await mountEntry(makeRun({ id: 5, agent_id: 1, outcome: 'running', session_id: 'run1' }))
    await w.find('[data-test="run-entry-cancel"]').trigger('click')
    await flushPromises()
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(w.find('[role="alert"]').text()).toContain('Não deu para cancelar.')
  })

  it('does not load any session for a finished run', async () => {
    await mountEntry(makeRun({ outcome: 'concluded', session_id: 'run1', ended_at: 1_790_000_060 }))
    expect(load).not.toHaveBeenCalled()
  })
})
