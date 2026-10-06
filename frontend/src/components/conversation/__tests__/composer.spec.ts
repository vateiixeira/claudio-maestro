import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MessageComposer from '../MessageComposer.vue'
import { resetComposerDrafts } from '../../../conversation/composerDrafts'
import { jsonResponse, routeFetch } from '../../../test/factories'

afterEach(() => vi.unstubAllGlobals())
beforeEach(resetComposerDrafts)

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
})
