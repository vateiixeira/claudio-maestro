import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import TextBlock from '../TextBlock.vue'

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

describe('acompanhar o fim com suavidade', () => {
  const reduceMotion = (reduce: boolean) =>
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: reduce && query.includes('reduce'), media: query, addEventListener() {}, removeEventListener() {} }))
  function spyScroll(scroller: { element: Element }) {
    const spy = vi.fn()
    ;(scroller.element as HTMLElement).scrollTo = spy as never
    return spy
  }
  // Distance from the end, with a scroll height of 2000 and a viewport of 400.
  const nearEnd = (distance: number) => 2000 - 400 - distance

  it('conteúdo novo a menos de 80px do fim rola suave até o fim, sem mostrar o botão', async () => {
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(70))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'smooth' })
    expect(jump(w).exists()).toBe(false)
  })

  it('a 80px ou mais do fim, nada se mexe e aparece "Novidades abaixo"', async () => {
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(80))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(spy).not.toHaveBeenCalled()
    expect((scroller.element as HTMLElement).scrollTop).toBe(nearEnd(80))
    expect(jump(w).text()).toContain('Novidades abaixo')
  })

  it('com movimento reduzido a rolagem é instantânea', async () => {
    reduceMotion(true)
    const { scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(10))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'auto' })
    expect(spy).not.toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth' }))
  })

  it('texto transmitindo só acompanha o fim, sem animar a rolagem', async () => {
    const { scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(10))
    emit('item.upsert', { ...text('a'), text: 'texto a, mais um pouco' }, 2)
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'auto' })
  })

  it('enquanto a rolagem suave corre, o avanço para baixo não conta como sair do fim', async () => {
    const { w, scroller } = await mountScrolled()
    spyScroll(scroller)
    await scrollTo(scroller, nearEnd(10))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    // Mid-glide: far from the new end, but moving down.
    await scrollTo(scroller, nearEnd(300))
    await scrollTo(scroller, nearEnd(200))
    emit('item.upsert', text('c'), 3)
    await flushPromises()
    expect(jump(w).exists()).toBe(false)
  })

  it('"Novidades abaixo" rola suave até o fim', async () => {
    const first = await mountScrolled()
    const spy = spyScroll(first.scroller)
    await scrollTo(first.scroller, 0)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    await jump(first.w).trigger('click')
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'smooth' })
  })

  it('"Novidades abaixo" com movimento reduzido rola instantâneo', async () => {
    reduceMotion(true)
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, 0)
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    await jump(w).trigger('click')
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'auto' })
  })
})

describe('primeira carga', () => {
  it('o histórico que chega no carregamento vai ao fim de uma vez, não rola suave do topo', async () => {
    const calls: unknown[] = []
    ;(Element.prototype as unknown as { scrollTo: unknown }).scrollTo = function (options: unknown) { calls.push(options) }
    try {
      await mountScrolled()
    } finally {
      delete (Element.prototype as unknown as { scrollTo?: unknown }).scrollTo
    }
    expect(calls.length).toBeGreaterThan(0)
    expect(calls.every((c) => (c as { behavior: string }).behavior === 'auto')).toBe(true)
  })
})

describe('acompanhar o texto que vai sendo revelado', () => {
  const nearEnd = (distance: number) => 2000 - 400 - distance
  const reveal = (w: Awaited<ReturnType<typeof mountScrolled>>['w']) => w.findComponent(TextBlock).vm.$emit('reveal')
  function spyScroll(scroller: { element: Element }) {
    const spy = vi.fn()
    ;(scroller.element as HTMLElement).scrollTo = spy as never
    return spy
  }

  it('quem estava a menos de 80px do fim continua acompanhando, sem animar a rolagem', async () => {
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(70))
    reveal(w)
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'auto' })
    expect(jump(w).exists()).toBe(false)
  })

  it('quem subiu para ler não é puxado, e o botão não aparece só por isso', async () => {
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(120))
    reveal(w)
    await flushPromises()
    expect(spy).not.toHaveBeenCalled()
    expect((scroller.element as HTMLElement).scrollTop).toBe(nearEnd(120))
    expect(jump(w).exists()).toBe(false)
  })

  it('depois de um item novo, o texto revelado se une à rolagem suave em curso', async () => {
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(10))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    spy.mockClear()
    reveal(w)
    expect(spy).toHaveBeenCalledWith({ top: 2000, behavior: 'smooth' })
  })

  it('com movimento reduzido nunca é suave', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query, addEventListener() {}, removeEventListener() {} }))
    const { w, scroller } = await mountScrolled()
    const spy = spyScroll(scroller)
    await scrollTo(scroller, nearEnd(10))
    emit('item.upsert', text('b'), 2)
    await flushPromises()
    reveal(w)
    expect(spy).not.toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth' }))
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
