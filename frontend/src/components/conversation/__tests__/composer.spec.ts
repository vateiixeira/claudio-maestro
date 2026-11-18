import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MessageComposer from '../MessageComposer.vue'
import { resetComposerDrafts } from '../../../conversation/composerDrafts'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { useTerminalStore } from '../../../stores/terminal'

afterEach(() => vi.unstubAllGlobals())
beforeEach(() => {
  resetComposerDrafts()
  setActivePinia(createPinia())
})

const URL = 'POST /api/sessions/s1/messages'
function setup(status = 202, body: unknown = {}) {
  const fetchMock = routeFetch({
    [URL]: () => jsonResponse(body, status),
    'POST /api/sessions/s1/interrupt': () => jsonResponse({}, 202),
  })
  vi.stubGlobal('fetch', fetchMock)
  const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
  return { w, fetchMock, ta: w.find('textarea') }
}
const sent = (m: ReturnType<typeof routeFetch>) => m.mock.calls.filter((c) => c[0] === '/api/sessions/s1/messages')

describe('campo de mensagem', () => {
  it('Enter envia e limpa', async () => {
    const { fetchMock, ta } = setup()
    await ta.setValue('olá')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(JSON.parse(sent(fetchMock)[0]![1]!.body as string)).toEqual({ text: 'olá' })
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
  })

  it('Ctrl+Enter e Shift+Enter não enviam', async () => {
    const { fetchMock, ta } = setup()
    await ta.setValue('a')
    await ta.trigger('keydown', { key: 'Enter', ctrlKey: true })
    await ta.trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()
    expect(sent(fetchMock)).toHaveLength(0)
  })

  it('Ctrl+Enter insere quebra de linha', async () => {
    const { ta } = setup()
    await ta.setValue('a')
    const el = ta.element as HTMLTextAreaElement
    el.setSelectionRange(1, 1)
    await ta.trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect(el.value).toBe('a\n')
  })

  it('Enter durante composição de IME não envia', async () => {
    const { fetchMock, ta } = setup()
    await ta.setValue('a')
    await ta.trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(sent(fetchMock)).toHaveLength(0)
  })

  it('texto vazio não envia', async () => {
    const { fetchMock, ta } = setup()
    await ta.setValue('   ')
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(sent(fetchMock)).toHaveLength(0)
  })

  it('Enviar desativado fica neutro, sem opacidade; ativo fica verde', async () => {
    const { w, ta } = setup()
    const send = w.find('[data-test="send"]')
    expect(send.attributes('disabled')).toBeDefined()
    expect(send.classes()).toEqual(expect.arrayContaining(['disabled:bg-elevated', 'disabled:text-fg-subtle']))
    expect(send.classes().some((c) => c.includes('opacity'))).toBe(false)
    expect(send.classes()).toContain('bg-primary')
    await ta.setValue('olá')
    expect(send.attributes('disabled')).toBeUndefined()
  })

  it('erro mantém o texto e mostra o detail', async () => {
    const { w, ta } = setup(503, { detail: 'O servidor está encerrando.' })
    await ta.setValue('olá')
    await w.find('[data-test="send"]').trigger('click')
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('olá')
    expect(w.find('[role="alert"]').text()).toContain('O servidor está encerrando.')
    expect(w.find('[role="alert"]').classes()).not.toContain('text-secondary')
  })

  it('"Interromper" só aparece rodando e chama a API', async () => {
    const { w, fetchMock } = setup()
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
    await w.setProps({ state: 'running' })
    await w.find('[data-test="interrupt"]').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s1/interrupt', expect.objectContaining({ method: 'POST' }))
  })

  it('"Interromper" aparece aguardando decisão e some conectando', async () => {
    const { w } = setup()
    await w.setProps({ state: 'awaiting_decision' })
    expect(w.find('[data-test="interrupt"]').exists()).toBe(true)
    await w.setProps({ state: 'connecting' })
    expect(w.find('[data-test="interrupt"]').exists()).toBe(false)
  })

  describe('trechos do terminal', () => {
    it('anexo do store aparece como chip com a primeira linha', async () => {
      const { w } = setup()
      useTerminalStore().attach('s1', 'primeira linha\nsegunda')
      await flushPromises()
      const chip = w.find('[data-test="terminal-attachment"]')
      expect(chip.exists()).toBe(true)
      expect(chip.text()).toContain('Trecho do terminal')
      expect(chip.text()).toContain('primeira linha')
      expect(chip.text()).not.toContain('segunda')
    })

    it('corta a primeira linha em 60 caracteres', async () => {
      const { w } = setup()
      useTerminalStore().attach('s1', 'x'.repeat(80))
      await flushPromises()
      const text = w.find('[data-test="terminal-attachment"]').text()
      expect(text).toContain('x'.repeat(60))
      expect(text).not.toContain('x'.repeat(61))
    })

    it('anexo de outra sessão não aparece', async () => {
      const { w } = setup()
      useTerminalStore().attach('s2', 'outra')
      await flushPromises()
      expect(w.find('[data-test="terminal-attachment"]').exists()).toBe(false)
    })

    it('enviar manda o trecho citado antes do texto e limpa o chip', async () => {
      const { w, fetchMock, ta } = setup()
      const store = useTerminalStore()
      store.attach('s1', 'linha')
      await ta.setValue('e isso?')
      await w.find('[data-test="send"]').trigger('click')
      await flushPromises()
      expect(JSON.parse(sent(fetchMock)[0]![1]!.body as string)).toEqual({ text: '<!-- attach: Terminal -->\n> linha\n\ne isso?' })
      expect(w.find('[data-test="terminal-attachment"]').exists()).toBe(false)
      expect(store.attachments['s1']).toBeUndefined()
    })

    it('remover o chip tira o anexo do store', async () => {
      const { w } = setup()
      const store = useTerminalStore()
      store.attach('s1', 'linha')
      await flushPromises()
      const button = w.find('[data-test="terminal-attachment"] button')
      expect(button.attributes('aria-label')).toBe('Remover trecho do terminal')
      await button.trigger('click')
      expect(w.find('[data-test="terminal-attachment"]').exists()).toBe(false)
      expect(store.attachments['s1']).toBeUndefined()
    })

    it('só com o anexo, Enviar fica habilitado', async () => {
      const { w } = setup()
      const send = w.find('[data-test="send"]')
      expect(send.attributes('disabled')).toBeDefined()
      useTerminalStore().attach('s1', 'linha')
      await flushPromises()
      expect(send.attributes('disabled')).toBeUndefined()
    })

    it('falha no envio mantém o anexo', async () => {
      const { w, ta } = setup(503, { detail: 'O servidor está encerrando.' })
      const store = useTerminalStore()
      store.attach('s1', 'linha')
      await ta.setValue('e isso?')
      await w.find('[data-test="send"]').trigger('click')
      await flushPromises()
      expect(store.attachments['s1']).toEqual(['linha'])
      expect(w.find('[data-test="terminal-attachment"]').exists()).toBe(true)
    })

    it('os anexos sobrevivem a trocar de sessão', async () => {
      const first = setup()
      useTerminalStore().attach('s1', 'linha')
      first.w.unmount()
      const again = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
      await flushPromises()
      expect(again.find('[data-test="terminal-attachment"]').exists()).toBe(true)
    })
  })
})

it('composer compacto do CTO mantém campo/envio e oferece controles por disclosure', async () => {
  const wrapper = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle', compactOnMobile: true }, slots: { controls: '<button>Modelo e permissões</button>' } })
  const toggle = wrapper.get('[data-test="composer-options-toggle"]')
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(wrapper.get('[data-test="composer-options"]').classes()).not.toContain('mobile-expanded')
  expect(wrapper.find('textarea').exists()).toBe(true)
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  expect(wrapper.get('[data-test="composer-options"]').classes()).toContain('mobile-expanded')
  expect(wrapper.get('[data-test="composer-options"]').text()).toContain('Modelo e permissões')
})

describe('moldura única do compositor', () => {
  const inside = (outer: Element, inner: Element) => outer !== inner && outer.contains(inner)
  const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

  it('o conteúdo do slot top, o campo e a barra de ferramentas ficam dentro da moldura, nessa ordem', () => {
    const w = mount(MessageComposer, {
      props: { sessionId: 's1', state: 'idle' },
      slots: { top: '<div data-test="top-slot">faixa</div>', controls: '<button data-test="ctl">Modelo</button>' },
      attachTo: document.body,
    })
    const frame = w.get('[data-test="composer-frame"]').element
    const top = w.get('[data-test="top-slot"]').element
    const ta = w.get('textarea').element
    const toolbar = w.get('[data-test="composer-toolbar"]').element
    expect(inside(frame, top)).toBe(true)
    expect(inside(frame, ta)).toBe(true)
    expect(inside(frame, toolbar)).toBe(true)
    expect(before(top, ta)).toBe(true)
    expect(before(ta, toolbar)).toBe(true)
    w.unmount()
  })

  it('a moldura não corta a lista de / e @: sem overflow escondido, e a borda e o foco são dela', () => {
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
    const frame = w.get('[data-test="composer-frame"]')
    expect(frame.classes()).not.toContain('overflow-hidden')
    expect(frame.classes()).toContain('border')
    expect(frame.classes()).toContain('focus-within:border-fg-muted')
    expect(w.get('textarea').classes()).not.toContain('border')
  })

  it('Enviar, Interromper e Ditar ficam na barra, depois das opções', () => {
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'running' }, slots: { controls: '<button>Modelo</button>' }, attachTo: document.body })
    const toolbar = w.get('[data-test="composer-toolbar"]').element
    const options = w.get('[data-test="composer-options"]').element
    expect(inside(toolbar, options)).toBe(true)
    const buttons = ['send', 'interrupt'].map((name) => w.get(`[data-test="${name}"]`).element)
    for (const button of buttons) {
      expect(inside(toolbar, button)).toBe(true)
      expect(inside(options, button)).toBe(false)
      expect(before(options, button)).toBe(true)
    }
    const dictate = w.find('[data-test="dictate"]')
    if (dictate.exists()) {
      expect(inside(toolbar, dictate.element)).toBe(true)
      expect(before(options, dictate.element)).toBe(true)
    }
    w.unmount()
  })

  it('Ditar, Interromper e Enviar ficam num contêiner próprio que não encolhe, depois das opções, que são quem encolhe e quebra', () => {
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'running' }, slots: { controls: '<button>Modelo</button>' }, attachTo: document.body })
    const actions = w.get('[data-test="composer-actions"]')
    const options = w.get('[data-test="composer-options"]')
    expect(actions.classes()).toContain('shrink-0')
    expect(actions.element.parentElement).toBe(w.get('[data-test="composer-toolbar"]').element)
    expect(before(options.element, actions.element)).toBe(true)
    expect(inside(actions.element, options.element)).toBe(false)
    for (const name of ['send', 'interrupt']) expect(inside(actions.element, w.get(`[data-test="${name}"]`).element)).toBe(true)
    if (w.find('[data-test="dictate"]').exists()) expect(inside(actions.element, w.get('[data-test="dictate"]').element)).toBe(true)
    // A base mínima (12rem) faz a coluna estreita descer os botões juntos, em vez de passar os controles por baixo deles.
    expect(options.classes()).toEqual(expect.arrayContaining(['min-w-0', 'flex-wrap', 'grow', 'basis-48']))
    expect(options.classes()).not.toContain('basis-0')
    w.unmount()
  })

  it('o hover dos botões de menu da barra usa card: fg-subtle não passa de 4,5:1 sobre elevated', () => {
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
    const classes = w.get('[data-test="composer-toolbar"]').classes().join(' ')
    expect(classes).toContain(':hover]:bg-card')
    expect(classes).not.toContain(':hover]:bg-elevated')
  })

  it('não mostra a dica de teclas no compositor', () => {
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' }, attachTo: document.body })
    expect(w.find('[data-test="composer-hint"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Enter envia')
    w.unmount()
  })

  it('os anexos ficam fora da moldura, antes dela', async () => {
    const { w } = setup()
    useTerminalStore().attach('s1', 'ls\nfoo')
    await flushPromises()
    const frame = w.get('[data-test="composer-frame"]').element
    const snippet = w.get('[data-test="terminal-attachment"]').element
    expect(inside(frame, snippet)).toBe(false)
    expect(before(snippet, frame)).toBe(true)
    w.unmount()
  })
})
