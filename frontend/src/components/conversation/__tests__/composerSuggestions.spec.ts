import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MessageComposer from '../MessageComposer.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { FakeRecognition } from '../../../test/fakeRecognition'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const COMMANDS = [
  { name: 'commit', description: 'Cria commit', argument_hint: '' },
  { name: 'hello', description: 'Diz olá', argument_hint: '<nome>' },
]

function setup() {
  const fetchMock = routeFetch({
    'GET /api/sessions/s1/commands': () => jsonResponse(COMMANDS),
    'POST /api/sessions/s1/messages': () => jsonResponse({}, 202),
  })
  vi.stubGlobal('fetch', fetchMock)
  const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' }, attachTo: document.body })
  const ta = w.get('textarea')
  const el = ta.element as HTMLTextAreaElement
  async function type(value: string) {
    await ta.setValue(value)
    el.setSelectionRange(value.length, value.length)
    await ta.trigger('input')
    await flushPromises()
  }
  const sent = () => fetchMock.mock.calls.filter((c) => c[0] === '/api/sessions/s1/messages')
  return { w, ta, el, type, sent }
}

describe('MessageComposer com sugestões', () => {
  it('Enter com menu aberto escolhe e não envia', async () => {
    const { w, ta, type, sent } = setup()
    await type('/co')
    expect(w.find('[role="listbox"]').exists()).toBe(true)
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
    expect(sent()).toHaveLength(0)
    expect(w.find('[role="listbox"]').exists()).toBe(false)
  })

  it('com menu fechado, Enter envia como hoje', async () => {
    const { ta, type, sent } = setup()
    await type('/commit agora')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(sent()).toHaveLength(1)
  })

  it('combobox com aria-expanded, aria-controls e aria-activedescendant', async () => {
    const { w, ta, type } = setup()
    expect(ta.attributes('role')).toBe('combobox')
    expect(ta.attributes('aria-expanded')).toBe('false')
    await type('/')
    expect(ta.attributes('aria-expanded')).toBe('true')
    const menu = w.get('[role="listbox"]')
    expect(ta.attributes('aria-controls')).toBe(menu.attributes('id'))
    expect(ta.attributes('aria-activedescendant')).toBe(w.get('[role="option"]').attributes('id'))
  })

  it('clique no item escolhe', async () => {
    const { w, ta, type } = setup()
    await type('/co')
    await w.get('[role="option"]').trigger('click')
    expect((ta.element as HTMLTextAreaElement).value).toBe('/commit ')
  })

  it('ditado fecha o menu aberto e o texto ditado não o abre', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w, type } = setup()
    await type('/co')
    expect(w.find('[role="listbox"]').exists()).toBe(true)
    await w.get('[data-test="dictate"]').trigger('click')
    expect(w.find('[role="listbox"]').exists()).toBe(false)
    FakeRecognition.last!.emit(['/ditado', true])
    await flushPromises()
    expect((w.get('textarea').element as HTMLTextAreaElement).value).toContain('/ditado')
    expect(w.find('[role="listbox"]').exists()).toBe(false)
  })

  it('enviar fecha o menu', async () => {
    const { w, type, sent } = setup()
    await type('/co')
    await w.get('[data-test="send"]').trigger('click')
    await flushPromises()
    expect(sent()).toHaveLength(1)
    expect(w.find('[role="listbox"]').exists()).toBe(false)
  })
})

describe('MessageComposer com a camada espelhada', () => {
  it('a camada aparece atrás do campo com o mesmo texto', async () => {
    const { w, ta, type } = setup()
    await type('/co')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    const mirror = w.get('div[aria-hidden="true"]')
    expect(mirror.text()).toContain('/commit')
    expect(mirror.text()).not.toContain('<nome>')
  })

  it('mostra a dica de argumentos depois de escolher o comando', async () => {
    const { w, ta, type } = setup()
    await type('/he')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.get('div[aria-hidden="true"]').text()).toContain('<nome>')
  })
})
