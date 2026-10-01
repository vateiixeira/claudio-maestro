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
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1 })
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
})
afterEach(() => vi.unstubAllGlobals())

const text = (id: string) => ({ type: 'text', id, text: `texto ${id}`, streaming: false, parent_tool_use_id: null })
const emit = (type: string, data: unknown, seq: number) => fake.session.get('s1')!(makeEvent(type, data, seq))

async function mountScrolled() {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'idle', items: [text('a')] as never })),
    'POST /api/sessions/s1/messages': () => jsonResponse({}),
  }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, attachTo: document.body, global: { plugins: [pinia, router] } })
  await flushPromises()
  const scroller = w.find('[data-test="conversation-scroller"]')
  Object.defineProperty(scroller.element, 'scrollHeight', { configurable: true, value: 2000 })
  Object.defineProperty(scroller.element, 'clientHeight', { configurable: true, value: 400 })
  return { w, scroller }
}
async function scrollTo(scroller: { element: Element; trigger: (e: string) => Promise<void> }, top: number) {
  scroller.element.scrollTop = top
  await scroller.trigger('scroll')
}
const jump = (w: Awaited<ReturnType<typeof mountScrolled>>['w']) => w.find('[data-test="jump-to-end"]')

describe('Ir para o fim', () => {
  it('não aparece quando o usuário está no fim e chega item novo', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 1600)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(jump(w).exists()).toBe(false)
  })

  it('aparece neutro, como botão, com "Novidades abaixo" quando chega item novo rolado para cima', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    expect(jump(w).exists()).toBe(false)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    const button = jump(w)
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('type')).toBe('button')
    expect(button.text()).toContain('Novidades abaixo')
    expect(button.classes()).toContain('bg-card')
    expect(button.classes()).toContain('border-line-strong')
    expect(button.classes()).toContain('text-fg')
    expect(button.classes()).toContain('min-h-8')
    expect(button.classes().join(' ')).toContain('focus-visible:outline')
    expect(button.classes()).not.toContain('bg-secondary')
  })

  it('"Pedido abaixo" em laranja quando chega permissão, pergunta ou plano', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('prompt.request', { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }, 2)
    await flushPromises()
    expect(jump(w).text()).toContain('Pedido abaixo')
    expect(jump(w).classes()).toContain('bg-secondary')
    expect(jump(w).classes()).not.toContain('bg-card')
  })

  it('pedido prevalece sobre novidade que chega depois', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('prompt.request', { prompt_id: 'p1', kind: 'plan', tool_name: 'ExitPlanMode', input: {}, can_always: false, plan: '# P' }, 2)
    emit('item.upsert', text('b'), 3)
    await flushPromises()
    expect(jump(w).text()).toContain('Pedido abaixo')
  })

  it('clicar rola até o fim e some', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    await jump(w).trigger('click')
    expect((scroller.element as HTMLElement).scrollTop).toBe(2000)
    expect(jump(w).exists()).toBe(false)
  })

  it('mensagem enviada pelo próprio usuário rola até o fim em vez de mostrar "Novidades abaixo"', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    await w.find('textarea').setValue('olá')
    await w.find('[data-test="send"]').trigger('click')
    emit('item.upsert', { type: 'user', id: 'u1', text: 'olá' }, 2)
    await flushPromises()
    expect((scroller.element as HTMLElement).scrollTop).toBe(2000)
    expect(jump(w).exists()).toBe(false)
  })

  it('mensagem de usuário que não foi enviada aqui continua só avisando', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('item.upsert', { type: 'user', id: 'u1', text: 'veio do terminal' }, 2)
    await flushPromises()
    expect(jump(w).text()).toContain('Novidades abaixo')
  })

  it('"Pedido abaixo": depois de rolar, o foco vai para o cartão do pedido', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('prompt.request', { prompt_id: 'p1', tool_name: 'Bash', input: { command: 'ls' }, can_always: false }, 2)
    await flushPromises()
    await jump(w).trigger('click')
    await flushPromises()
    const card = w.find('[data-test="permission-card"]')
    expect(card.attributes('tabindex')).toBe('-1')
    expect(document.activeElement).toBe(card.element)
  })

  it('some sozinho quando o usuário chega ao fim', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(jump(w).exists()).toBe(true)
    await scrollTo(scroller, 1580)
    expect(jump(w).exists()).toBe(false)
  })

  it('depois de sumir, só volta com novidade nova', async () => {
    const { w, scroller } = await mountScrolled()
    await scrollTo(scroller, 0)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    await scrollTo(scroller, 1580)
    await scrollTo(scroller, 0)
    expect(jump(w).exists()).toBe(false)
    emit('item.upsert', text('c'), 3)
    await flushPromises()
    expect(jump(w).text()).toContain('Novidades abaixo')
  })
})

describe('erro de carga em vermelho', () => {
  it('usa as cores de erro, não o laranja', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse({ detail: 'Servidor caiu.' }, 500) }))
    const router = createAppRouter(createMemoryHistory())
    await router.push('/sessions/s1')
    const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
    await flushPromises()
    const alert = w.find('[role="alert"]')
    expect(alert.classes()).toContain('text-diff-del-fg')
    expect(alert.classes()).not.toContain('text-secondary-soft')
  })
})
