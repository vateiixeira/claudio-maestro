import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'

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
})
afterEach(() => vi.unstubAllGlobals())

const user = (id: string) => ({ type: 'user', id, text: `pergunta ${id}` })
const text = (id: string, t = `texto ${id}`) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: null })
const tool = (id: string) => ({ type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Bash', input: { command: 'ls' }, result: null, streaming: false, parent_tool_use_id: null })
const bash = { prompt_id: 'p0', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }

async function mountThread(items: unknown[], prompts: unknown[] = []) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, items: items as never, prompts: prompts as never })),
    'GET /api/sessions/s2': () => jsonResponse(makeSnapshot({ session_id: 's2', seq: 1, items: [text('x'), tool('t9')] as never })),
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}
const emit = (type: string, data: unknown, seq: number, id = 's1') => fake.session.get(id)!(makeEvent(type, data, seq, id))
type Wrapper = Awaited<ReturnType<typeof mountThread>>
const entries = (w: Wrapper) => w.findAll('[data-test="turn-entry"]')
const animated = (w: Wrapper, cls: string) => w.findAll(`.${cls}`)

describe('entrada só para o que chega ao vivo', () => {
  it('o histórico montado aparece sem nenhuma animação', async () => {
    const w = await mountThread([user('u1'), text('a'), tool('t1'), text('b')], [bash])
    expect(entries(w)).toHaveLength(3)
    expect(animated(w, 'animate-enter')).toHaveLength(0)
    expect(animated(w, 'animate-pop')).toHaveLength(0)
    expect(animated(w, 'animate-decision')).toHaveLength(0)
    expect(w.find('[data-test="permission-card"]').exists()).toBe(true)
  })

  it('um item que chega depois entra com animação, e o nó do trilho dele com pop', async () => {
    const w = await mountThread([user('u1'), text('a')])
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    const rows = entries(w)
    expect(rows).toHaveLength(2)
    expect(rows[0]!.classes()).not.toContain('animate-enter')
    expect(rows[0]!.find('[data-test="rail-dot"]').classes()).not.toContain('animate-pop')
    expect(rows[1]!.classes()).toContain('animate-enter')
    expect(rows[1]!.find('[data-test="rail-dot"]').classes()).toContain('animate-pop')
  })

  it('mensagem do usuário e bloco de trabalho que chegam ao vivo também entram', async () => {
    const w = await mountThread([user('u1'), text('a')])
    emit('item.upsert', user('u2'), 2)
    emit('item.upsert', tool('t1'), 3)
    await flushPromises()
    const rows = w.findAll('[data-test="user-message-row"]')
    expect(rows[0]!.classes()).not.toContain('animate-enter')
    expect(rows[1]!.classes()).toContain('animate-enter')
    const last = entries(w).at(-1)!
    expect(last.find('[data-test="work-block"]').exists() || last.find('[data-test="rail-ring"]').exists()).toBe(true)
    expect(last.classes()).toContain('animate-enter')
    expect(last.find('[data-test="rail-ring"]').classes()).toContain('animate-pop')
  })

  it('item que só muda (texto transmitindo, resultado chegando) não anima de novo', async () => {
    const w = await mountThread([user('u1'), text('a', 'um'), tool('t1')])
    emit('item.upsert', text('a', 'um dois três'), 2)
    emit('item.upsert', { ...tool('t1'), result: { content: 'ok', is_error: false } }, 3)
    await flushPromises()
    expect(w.text()).toContain('um dois três')
    expect(animated(w, 'animate-enter')).toHaveLength(0)
    expect(animated(w, 'animate-pop')).toHaveLength(0)
  })

  it('um item ao vivo não volta a animar quando outro chega, e um bloco de trabalho que cresce não anima de novo', async () => {
    const w = await mountThread([user('u1'), text('a')])
    emit('item.upsert', tool('t1'), 2)
    await flushPromises()
    const group = () => entries(w)[1]!.element
    const before = group()
    expect(entries(w)[1]!.classes()).toContain('animate-enter')
    emit('item.upsert', tool('t2'), 3)
    await flushPromises()
    // Same element, same group: the work block grew, it was not recreated.
    expect(group()).toBe(before)
    expect(entries(w)).toHaveLength(2)
  })

  it('pedido de decisão que chega ao vivo ganha a animação de decisão; o que já estava, não', async () => {
    const w = await mountThread([user('u1'), text('a')], [bash])
    expect(w.find('[data-test="permission-card"]').classes()).not.toContain('animate-decision')
    emit('prompt.request', { prompt_id: 'p1', kind: 'plan', tool_name: 'ExitPlanMode', input: {}, can_always: false, plan: '# P' }, 2)
    emit('prompt.request', { prompt_id: 'p2', kind: 'question', tool_name: 'AskUserQuestion', input: {}, can_always: false, questions: [{ question: 'Qual?', header: 'Q', multiSelect: false, options: [{ label: 'A', description: '' }, { label: 'B', description: '' }] }] }, 3)
    emit('prompt.request', { ...bash, prompt_id: 'p3' }, 4)
    await flushPromises()
    expect(w.find('[data-test="permission-card"]').classes()).not.toContain('animate-decision')
    expect(w.find('[data-test="plan-card"]').classes()).toContain('animate-decision')
    expect(w.find('[data-test="question-card"]').classes()).toContain('animate-decision')
    expect(w.findAll('[data-test="permission-card"]')[1]!.classes()).toContain('animate-decision')
  })

  it('trocar de conversa zera o conjunto: o histórico da nova não anima, o que chega nela sim', async () => {
    const w = await mountThread([user('u1'), text('a')])
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(animated(w, 'animate-enter')).toHaveLength(1)
    await w.setProps({ id: 's2' })
    await flushPromises()
    expect(w.text()).toContain('texto x')
    expect(entries(w)).toHaveLength(2)
    expect(animated(w, 'animate-enter')).toHaveLength(0)
    expect(animated(w, 'animate-pop')).toHaveLength(0)
    emit('item.upsert', text('y'), 2, 's2')
    await flushPromises()
    expect(animated(w, 'animate-enter')).toHaveLength(1)
    expect(entries(w).at(-1)!.classes()).toContain('animate-enter')
  })
})
