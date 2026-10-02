import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
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
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}

describe('faixa de subagentes na conversa', () => {
  it('aparece acima do campo de mensagem enquanto há subagente rodando', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), agent('a', 'running'), child('r', 'tu-a')],
    })
    const strip = w.find('[data-test="subagent-strip"]')
    expect(strip.exists()).toBe(true)
    expect(strip.text()).toContain('desc a')
    expect(strip.text()).toContain('Read r.py')
    const composer = w.find('textarea')
    expect(strip.element.compareDocumentPosition(composer.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('com a sessão ociosa e um subagente em segundo plano, "Parar subagente" chama a rota da sessão', async () => {
    const fetchMock = routeFetch({
      'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'idle', items: [user('u1'), agent('bg', 'running'), user('u2')] as never })),
      'POST /api/sessions/s1/subagents/stop': () => jsonResponse({}, 202),
    })
    vi.stubGlobal('fetch', fetchMock)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
    const stop = w.find('[data-test="subagent-stop"]')
    expect(stop.text()).toBe('Parar subagente')
    await stop.trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s1/subagents/stop', expect.objectContaining({ method: 'POST' }))
  })

  it('não aparece quando todos terminaram', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), agent('a', 'completed'), agent('b', 'failed')] })
    expect(w.find('[data-test="subagent-strip"]').exists()).toBe(false)
  })

  it('subagente em segundo plano de turno anterior mantém a faixa depois de a sessão ficar ociosa', async () => {
    const w = await mountWith({
      state: 'idle',
      items: [user('u1'), agent('bg', 'running'), user('u2')],
    })
    expect(w.find('[data-test="subagent-strip"]').text()).toContain('desc bg')
  })

  it('mantém os concluídos enquanto outro roda e some quando o último termina', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), agent('a', 'completed'), agent('b', 'running')],
    })
    expect(w.findAll('[data-test="subagent-row"]')).toHaveLength(2)
    fake.session.get('s1')!(makeEvent('item.upsert', agent('b', 'completed'), 2))
    await flushPromises()
    expect(w.find('[data-test="subagent-strip"]').exists()).toBe(false)
  })

  it('clicar leva ao cartão, abre e destaca', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), agent('a', 'completed'), child('r', 'tu-a'), agent('b', 'running')],
    })
    const card = w.find('[data-subagent-id="a"]')
    expect(card.exists()).toBe(true)
    expect(card.find('[data-test="subagent-children"]').isVisible()).toBe(false)
    const scrollIntoView = vi.fn()
    ;(card.element as HTMLElement).scrollIntoView = scrollIntoView
    await w.findAll('[data-test="subagent-row"]')[0]!.trigger('click')
    await flushPromises()
    expect(scrollIntoView).toHaveBeenCalled()
    expect(card.find('[data-test="subagent-children"]').isVisible()).toBe(true)
    expect(card.attributes('data-highlighted')).toBe('true')
  })

  it('cartão de subagente rodando começa fechado e abre ao clicar na faixa', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), agent('a', 'completed'), agent('b', 'running'), child('r', 'tu-b')],
    })
    const card = w.find('[data-subagent-id="b"]')
    expect(card.find('[data-test="subagent-children"]').isVisible()).toBe(false)
    ;(card.element as HTMLElement).scrollIntoView = vi.fn()
    await w.findAll('[data-test="subagent-row"]')[1]!.trigger('click')
    await flushPromises()
    expect(card.find('[data-test="subagent-children"]').isVisible()).toBe(true)
  })

  it('cartão de subagente aninhado abre também o de fora', async () => {
    const w = await mountWith({
      state: 'running',
      items: [
        user('u1'),
        agent('outer', 'completed'),
        agent('inner', 'running', { parent_tool_use_id: 'tu-outer' }),
      ],
    })
    const outer = w.find('[data-subagent-id="outer"]')
    expect(outer.find('[data-test="subagent-children"]').isVisible()).toBe(false)
    await w.findAll('[data-test="subagent-row"]')[1]!.trigger('click')
    await flushPromises()
    expect(outer.find('[data-test="subagent-children"]').isVisible()).toBe(true)
    expect(w.find('[data-subagent-id="inner"]').attributes('data-highlighted')).toBe('true')
  })
})
