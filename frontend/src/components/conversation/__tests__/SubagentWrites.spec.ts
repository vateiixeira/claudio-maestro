import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'

const fake = vi.hoisted(() => ({ session: new Map<string, (e: unknown) => void>() }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
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
  fake.session.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
})
afterEach(() => vi.unstubAllGlobals())

const user = (id: string) => ({ type: 'user', id, text: id })
const subagent = (status: string, extra: Record<string, unknown> = {}) => ({
  task_id: 't', subagent_type: 'reviewer', description: 'Revisar', status, last_activity: null, usage: null, summary: null, ...extra,
})
const agent = (id: string, status: string, extra: Record<string, unknown> = {}) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Agent', input: { subagent_type: 'reviewer', description: `desc ${id}` },
  result: null, streaming: false, parent_tool_use_id: null, subagent: subagent(status, { description: `desc ${id}` }), ...extra,
})
const child = (id: string, parent: string, name = 'Read', input: Record<string, unknown> = { file_path: `/p/${id}.py` }) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input,
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: parent,
})

async function mountWith(snapshot: Record<string, unknown>) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, ...snapshot })) }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, // Real transition: the shortcut learns about openings from its hooks.
    global: { plugins: [pinia, router], stubs: { transition: false } }, attachTo: document.body })
  await flushPromises()
  return w
}


const write = (id: string, parent: string, file: string) => child(id, parent, 'Write', { file_path: file, content: 'x' })

describe('escritas de subagente na conversa', () => {
  it('aparecem como ações do bloco, com o nome do subagente, e continuam no cartão', async () => {
    const w = await mountWith({
      state: 'idle',
      items: [user('u1'), agent('a', 'completed'), child('r', 'tu-a'), write('w1', 'tu-a', '/p/novo.py'), write('w2', 'tu-a', '/p/outro.py')],
    })
    const block = w.find('[data-test="work-block"]')
    // The block holds the subagent and its two writes; the read stays in the card.
    expect(block.find('[data-test="work-count"]').text()).toBe('3 ações')
    // A finished turn's block starts closed.
    await block.find('[data-test="work-block-toggle"]').trigger('click')
    await flushPromises()
    const rows = block.findAll('[data-test="work-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[1]!.find('[data-test="work-tag"]').text()).toBe('reviewer')
    expect(rows[1]!.find('[data-test="work-desc"]').text()).toBe('/p/novo.py')
    expect(rows[2]!.find('[data-test="work-desc"]').text()).toBe('/p/outro.py')
    // The write is also in the card: open the subagent row and count the cards inside it.
    await rows[0]!.find('[data-test="work-header"]').trigger('click')
    await flushPromises()
    expect(rows[0]!.find('[data-test="subagent-children"]').exists()).toBe(true)
    // One count per action: the agent, the read and the two writes, not the writes twice.
    expect(w.find('[data-test="turn-end-summary"]').text()).toBe('· 4 ações · 2 arquivos alterados')
  })

  it('pedido de permissão de uma escrita do subagente marca a linha como esperando você, uma vez', async () => {
    const w = await mountWith({
      state: 'awaiting_decision',
      items: [user('u1'), agent('a', 'running'), { ...write('w1', 'tu-a', '/p/novo.py'), result: null }],
      prompts: [{ prompt_id: 'p1', tool_name: 'Write', input: { file_path: '/p/novo.py', content: 'x' }, tool_use_id: 'tu-w1', can_always: true }],
    })
    expect(w.findAll('[data-test="permission-card"]')).toHaveLength(1)
    // The block is folded while the turn runs; open it to see the rows.
    await w.find('[data-test="work-block-toggle"]').trigger('click')
    const rows = w.findAll('[data-test="work-row"]')
    expect(rows).toHaveLength(2)
    // Both the subagent that runs it and the write wait for the user.
    expect(rows.map((r) => r.find('[data-test="work-status"]').attributes('data-status'))).toEqual(['waiting', 'waiting'])
  })

  it('escrita do próprio agente não ganha chip', async () => {
    const w = await mountWith({
      state: 'idle',
      items: [user('u1'), { ...write('w', 'x', '/p/a.py'), parent_tool_use_id: null }],
    })
    expect(w.find('[data-test="work-row"] [data-test="work-tag"]').exists()).toBe(false)
  })
})
