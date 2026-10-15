import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
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
const scrollIntoView = vi.fn()

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  scrollIntoView.mockClear()
  Element.prototype.scrollIntoView = scrollIntoView
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const user = (id: string, t: string) => ({ type: 'user', id, text: t })
const text = (id: string, t: string, parent: string | null = null) => ({ type: 'text', id, text: t, streaming: false, parent_tool_use_id: parent })
const thinking = (id: string, t: string) => ({ type: 'thinking', id, text: t, streaming: false, parent_tool_use_id: null })

async function mountThread(items: unknown[], props: Record<string, unknown> = {}) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'idle', items: items as never })),
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, {
    props: { id: 's1', visible: true, ...props },
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  })
  await flushPromises()
  return w
}

const items = [
  user('u1', 'Como crio a jornada?'),
  text('a1', 'Na jornada do funil você monta uma regra'),
  user('u2', 'obrigado'),
  text('a2', 'De nada'),
]

describe('abrir a conversa na mensagem buscada', () => {
  it('rola até a última mensagem com o termo, a destaca e avisa que terminou', async () => {
    const w = await mountThread(items, { find: 'JORNADA' })

    const target = w.get('[data-item-id="a1"]')
    expect(scrollIntoView.mock.contexts.at(-1)).toBe(target.element)
    expect(target.attributes('data-highlighted')).toBe('true')
    expect(target.attributes('tabindex')).toBe('-1')
    expect(w.find('[data-item-id="u1"]').attributes('data-highlighted')).toBeUndefined()
    expect(w.find('[data-test="find-missed"]').exists()).toBe(false)
    expect(w.emitted('find-done')).toHaveLength(1)
  })

  it('a mensagem do usuário também pode ser o alvo', async () => {
    const w = await mountThread(items, { find: 'obrigado' })

    expect(w.get('[data-item-id="u2"]').attributes('data-highlighted')).toBe('true')
  })

  it('o destaque some depois de um instante', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
    const w = await mountThread(items, { find: 'jornada' })
    expect(w.get('[data-item-id="a1"]').attributes('data-highlighted')).toBe('true')

    await vi.advanceTimersByTimeAsync(2100)

    expect(w.get('[data-item-id="a1"]').attributes('data-highlighted')).toBeUndefined()
  })

  it('não mostra "Novidades abaixo" depois do salto', async () => {
    const w = await mountThread(items, { find: 'jornada' })

    expect(w.find('[data-test="jump-to-end"]').exists()).toBe(false)
  })

  it('sem a mensagem na conversa, abre no fim, avisa e não rola', async () => {
    const w = await mountThread(items, { find: 'inexistente' })

    expect(w.get('[data-test="find-missed"]').text()).toBe('A mensagem buscada não está no trecho carregado da conversa.')
    expect(scrollIntoView).not.toHaveBeenCalled()
    expect(w.emitted('find-done')).toHaveLength(1)
  })

  it('texto de subagente e raciocínio não contam', async () => {
    const w = await mountThread(
      [user('u1', 'oi'), text('a1', 'termo raro no subagente', 'tu-1'), thinking('t1', 'termo raro pensado')],
      { find: 'termo raro' },
    )

    expect(w.find('[data-test="find-missed"]').exists()).toBe(true)
    expect(w.find('[data-highlighted="true"]').exists()).toBe(false)
  })

  it('sem o termo, nada acontece', async () => {
    const w = await mountThread(items)

    expect(w.emitted('find-done')).toBeUndefined()
    expect(w.find('[data-test="find-missed"]').exists()).toBe(false)
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('o termo que chega com a conversa já aberta também leva à mensagem', async () => {
    const w = await mountThread(items)

    await w.setProps({ find: 'obrigado' })
    await flushPromises()

    expect(w.get('[data-item-id="u2"]').attributes('data-highlighted')).toBe('true')
    expect(w.emitted('find-done')).toHaveLength(1)
  })
})
