import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'

vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({ onSession: () => () => {}, onReconnect: () => () => {}, onOpen: () => () => {} }),
}))

import ConversationThread from '../ConversationThread.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
let scroll: ReturnType<typeof vi.fn>
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1 })
  scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll as never
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const user = (id: string, t = id) => ({ type: 'user', id, text: t })

async function mountThread(items: unknown[], visible = true) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'idle', items: items as never })) }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  // Three turns laid out at 0, 500 and 1000; the bar reads turn 2.
  const scroller = w.find('[data-test="conversation-scroller"]')
  Object.defineProperty(scroller.element, 'scrollHeight', { configurable: true, value: 10000 })
  Object.defineProperty(scroller.element, 'clientHeight', { configurable: true, value: 400 })
  const tops = [0, 500, 1000]
  w.findAll('[data-turn-anchor]').forEach((a, i) => Object.defineProperty(a.element, 'offsetTop', { configurable: true, value: tops[i] }))
  scroller.element.scrollTop = 520
  await scroller.trigger('scroll')
  return w
}
const THREE = [user('u1'), user('u2', 'segundo'), user('u3')]

function press(key: string, init: KeyboardEventInit = {}, target: Element | Document = document.body) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}
const anchors = (w: Awaited<ReturnType<typeof mountThread>>) => w.findAll('[data-turn-anchor]').map((a) => a.element)

describe('atalhos [ e ] entre turnos', () => {
  it('"]" vai ao próximo turno e "[" ao anterior, como os botões da barra', async () => {
    const w = await mountThread(THREE)
    expect(w.find('[data-test="turn-bar"]').text()).toContain('Turno 2 de 3')
    press(']')
    await flushPromises()
    expect(scroll).toHaveBeenCalledTimes(1)
    expect(scroll.mock.contexts[0]).toBe(anchors(w)[2])
    expect(w.find('[data-test="turn-bar"]').text()).toContain('Turno 3 de 3')
    press('[')
    press('[')
    await flushPromises()
    expect(scroll.mock.contexts[1]).toBe(anchors(w)[1])
    expect(scroll.mock.contexts[2]).toBe(anchors(w)[0])
  })

  it('não faz nada nos extremos e marca o evento como tratado quando navega', async () => {
    const w = await mountThread(THREE)
    press('[')
    await flushPromises()
    expect(w.find('[data-test="turn-bar"]').text()).toContain('Turno 1 de 3')
    scroll.mockClear()
    press('[')
    expect(scroll).not.toHaveBeenCalled()
    expect(press(']').defaultPrevented).toBe(true)
  })

  it('é ignorado dentro do campo de mensagem e de outros campos de texto', async () => {
    const w = await mountThread(THREE)
    const field = w.find('textarea').element
    press(']', {}, field)
    const input = document.createElement('input')
    document.body.appendChild(input)
    press(']', {}, input)
    const editable = document.createElement('div')
    editable.setAttribute('contenteditable', 'true')
    const inner = document.createElement('span')
    editable.appendChild(inner)
    document.body.appendChild(editable)
    press(']', {}, inner)
    expect(scroll).not.toHaveBeenCalled()
  })

  it.each([['ctrlKey'], ['metaKey'], ['altKey']])('é ignorado com %s', async (modifier) => {
    await mountThread(THREE)
    press(']', { [modifier]: true })
    expect(scroll).not.toHaveBeenCalled()
  })

  it('é ignorado quando a conversa não está visível', async () => {
    const w = await mountThread(THREE)
    await w.setProps({ visible: false })
    press(']')
    expect(scroll).not.toHaveBeenCalled()
    await w.setProps({ visible: true })
    press(']')
    expect(scroll).toHaveBeenCalledTimes(1)
  })

  it('é ignorado sem a barra de turnos (menos de dois turnos)', async () => {
    await mountThread([user('u1')])
    press(']')
    expect(scroll).not.toHaveBeenCalled()
  })

  it('remove o listener ao desmontar', async () => {
    const w = await mountThread(THREE)
    w.unmount()
    press(']')
    expect(scroll).not.toHaveBeenCalled()
  })

  it('os botões da barra anunciam o atalho', async () => {
    const w = await mountThread(THREE)
    const prev = w.find('[aria-label="Turno anterior"]')
    const next = w.find('[aria-label="Próximo turno"]')
    expect(prev.attributes('aria-keyshortcuts')).toBe('[')
    expect(prev.attributes('title')).toBe('Turno anterior ([)')
    expect(next.attributes('aria-keyshortcuts')).toBe(']')
    expect(next.attributes('title')).toBe('Próximo turno (])')
  })
})
