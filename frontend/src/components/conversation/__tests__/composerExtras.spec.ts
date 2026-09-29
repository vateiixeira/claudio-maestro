import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MessageComposer from '../MessageComposer.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { setPendingDraft } from '../../../conversation/pendingDrafts'
import { localImagesFor, claimLocalImages, forgetSessionImages, resetLocalImages } from '../../../conversation/localImages'

enableAutoUnmount(afterEach)
afterEach(() => {
  vi.unstubAllGlobals()
  resetLocalImages()
  pendingReads.length = 0
})

// jsdom's FileReader finishes after three chained macrotasks, so a fixed `setTimeout(0)` is not
// enough under load. Tracking each reader until `loadend` makes the wait deterministic.
const pendingReads: Promise<void>[] = []
const RealFileReader = FileReader
class TrackedFileReader extends RealFileReader {
  constructor() {
    super()
    pendingReads.push(new Promise<void>((resolve) => this.addEventListener('loadend', () => resolve())))
  }
}

function setup() {
  vi.stubGlobal('FileReader', TrackedFileReader)
  const fetchMock = routeFetch({ 'POST /api/sessions/s1/messages': () => jsonResponse({}, 202) })
  vi.stubGlobal('fetch', fetchMock)
  const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' }, attachTo: document.body })
  return { w, fetchMock, ta: w.find('textarea') }
}
const bodies = (m: ReturnType<typeof routeFetch>) =>
  m.mock.calls.filter((c) => c[0] === '/api/sessions/s1/messages').map((c) => JSON.parse(c[1]!.body as string))

function png(name = 'tela.png', bytes = 3, type = 'image/png') {
  return new File([new Uint8Array(bytes).fill(65)], name, { type })
}
/** Waits for every FileReader started so far, then for the component to apply the results. */
async function settleReads() {
  await flushPromises()
  await Promise.all(pendingReads)
  await flushPromises()
}
async function paste(ta: ReturnType<typeof setup>['ta'], files: File[]) {
  await ta.trigger('paste', { clipboardData: { files, items: files.map((f) => ({ kind: 'file', type: f.type, getAsFile: () => f })) } })
  await settleReads()
}

describe('imagens no campo', () => {
  it('colar mostra miniatura com nome e tamanho, e remove', async () => {
    const { w, ta } = setup()
    await paste(ta, [png('tela.png', 2048)])
    const chip = w.find('[data-test="attachment-draft"]')
    expect(chip.text()).toContain('tela.png')
    expect(chip.text()).toContain('2 KB')
    expect(chip.find('img').attributes('src')).toMatch(/^data:image\/png;base64,/)
    await chip.find('button[aria-label="Remover imagem tela.png"]').trigger('click')
    expect(w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('envia em base64 sem prefixo e aceita texto vazio', async () => {
    const { w, ta, fetchMock } = setup()
    await paste(ta, [png('a.png', 3)])
    expect(w.find('[data-test="send"]').attributes('disabled')).toBeUndefined()
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodies(fetchMock)).toEqual([{ text: '', images: [{ media_type: 'image/png', data: 'QUFB' }] }])
    expect(w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('guarda a miniatura para a mensagem desta aba', async () => {
    const { ta } = setup()
    await paste(ta, [png('a.png', 3)])
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    // An item from the CLI with other images does not take the thumbnail.
    claimLocalImages('s1', { type: 'user', id: 'cli', text: '', images: [{ type: 'image', media_type: 'image/png', size: 999 }] })
    expect(localImagesFor('cli')).toBeUndefined()
    claimLocalImages('s1', { type: 'user', id: 'u1', text: '', images: [{ type: 'image', media_type: 'image/png', size: 3 }] })
    expect(localImagesFor('u1')).toEqual(['data:image/png;base64,QUFB'])
    forgetSessionImages('s1')
    expect(localImagesFor('u1')).toBeUndefined()
  })

  it('valida formato, tamanho e quantidade', async () => {
    const { w, ta } = setup()
    await paste(ta, [png('doc.pdf', 3, 'application/pdf')])
    expect(w.find('[role="alert"]').text()).toContain('doc.pdf')
    await paste(ta, [png('grande.png', 5 * 1024 * 1024 + 1)])
    expect(w.find('[role="alert"]').text()).toContain('5 MB')
    await paste(ta, Array.from({ length: 11 }, (_, i) => png(`i${i}.png`)))
    expect(w.findAll('[data-test="attachment-draft"]')).toHaveLength(10)
    expect(w.find('[role="alert"]').text()).toContain('10 imagens')
  })

  it('recusa passar de 30 MB somando as imagens', async () => {
    const { w, ta } = setup()
    const big = (i: number) => {
      const file = png(`g${i}.png`)
      Object.defineProperty(file, 'size', { value: 5 * 1024 * 1024 })
      return file
    }
    await paste(ta, Array.from({ length: 7 }, (_, i) => big(i)))
    expect(w.findAll('[data-test="attachment-draft"]')).toHaveLength(6)
    expect(w.find('[role="alert"]').text()).toContain('30 MB')
  })

  it('colar texto sem imagem segue o normal', async () => {
    const { w, ta } = setup()
    await ta.trigger('paste', { clipboardData: { files: [], items: [] } })
    expect(w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('mostra as imagens de um primeiro prompt que não saiu', async () => {
    setPendingDraft('s1', { text: 'oi', error: 'Sem conexão.', images: [{ id: 1, name: 'a.png', size: 3, mediaType: 'image/png', url: 'data:image/png;base64,QUFB' }] })
    const { w } = setup()
    expect(w.find('[data-test="attachment-draft"]').text()).toContain('a.png')
    expect(w.find('[role="alert"]').text()).toContain('Sem conexão.')
  })

  it('arrastar imagem para o campo anexa', async () => {
    const { w } = setup()
    await w.trigger('drop', { dataTransfer: { files: [png('arrastada.webp', 3, 'image/webp')], types: ['Files'] } })
    await settleReads()
    expect(w.find('[data-test="attachment-draft"]').text()).toContain('arrastada.webp')
  })
})

class FakeRecognition {
  static last: FakeRecognition | null = null
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((e: unknown) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  onend: (() => void) | null = null
  started = false
  constructor() { FakeRecognition.last = this }
  start() { this.started = true }
  stop() { this.started = false; this.onend?.() }
  abort() { this.stop() }
  emit(...parts: Array<[string, boolean]>) {
    const results = parts.map(([t, isFinal]) => Object.assign([{ transcript: t, confidence: 1 }], { isFinal }))
    this.onresult?.({ resultIndex: 0, results })
  }
}

describe('ditado por voz', () => {
  it('sem suporte, o botão não aparece', () => {
    const { w } = setup()
    expect(w.find('[data-test="dictate"]').exists()).toBe(false)
  })

  it('grava, insere parcial no cursor, para e não envia sozinho', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w, ta, fetchMock } = setup()
    await ta.setValue('olá mundo')
    const el = ta.element as HTMLTextAreaElement
    el.setSelectionRange(3, 3)
    const mic = w.find('[data-test="dictate"]')
    expect(mic.attributes('aria-label')).toBe('Ditar mensagem')
    await mic.trigger('click')
    const rec = FakeRecognition.last!
    expect(rec.started).toBe(true)
    expect(rec.lang).toBe('pt-BR')
    expect(rec.interimResults).toBe(true)
    expect(w.find('[data-test="dictate"]').attributes('aria-pressed')).toBe('true')
    expect(w.text()).toContain('Gravando')

    rec.emit(['caro', false])
    await flushPromises()
    expect(el.value).toBe('olá caro mundo')
    rec.emit(['caro amigo', true])
    await flushPromises()
    expect(el.value).toBe('olá caro amigo mundo')

    await w.find('[data-test="dictate"]').trigger('click')
    expect(rec.started).toBe(false)
    expect(w.find('[data-test="dictate"]').attributes('aria-pressed')).toBe('false')
    await flushPromises()
    expect(bodies(fetchMock)).toEqual([])
  })

  it('resultado tardio depois do envio não reaparece', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w, ta, fetchMock } = setup()
    await w.find('[data-test="dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    rec.emit(['oi', false])
    await flushPromises()
    await ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodies(fetchMock)).toEqual([{ text: 'oi' }])
    rec.emit(['oi tudo bem', true])
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
  })

  it('digitar durante a gravação para o ditado e preserva o texto', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w, ta } = setup()
    await w.find('[data-test="dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    rec.emit(['oi', false])
    await flushPromises()
    await ta.setValue('oi, escrevi')
    expect(w.find('[data-test="dictate"]').attributes('aria-pressed')).toBe('false')
    rec.emit(['oi de novo', true])
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('oi, escrevi')
  })

  it('desmontar zera os handlers', async () => {
    vi.stubGlobal('webkitSpeechRecognition', FakeRecognition)
    const { w } = setup()
    await w.find('[data-test="dictate"]').trigger('click')
    const rec = FakeRecognition.last!
    w.unmount()
    expect(rec.onresult).toBeNull()
    expect(rec.onend).toBeNull()
    expect(rec.onerror).toBeNull()
  })

  it('erro de permissão mostra mensagem', async () => {
    vi.stubGlobal('SpeechRecognition', FakeRecognition)
    const { w } = setup()
    await w.find('[data-test="dictate"]').trigger('click')
    FakeRecognition.last!.onerror?.({ error: 'not-allowed' })
    FakeRecognition.last!.onend?.()
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('microfone')
    expect(w.find('[data-test="dictate"]').attributes('aria-pressed')).toBe('false')
  })
})

describe('erros do ditado', () => {
  it.each([
    ['audio-capture', 'Nenhum microfone encontrado.'],
    ['network', 'Sem conexão para o ditado.'],
  ])('%s mostra mensagem legível', async (code, message) => {
    vi.stubGlobal('SpeechRecognition', FakeRecognition)
    const { w } = setup()
    await w.find('[data-test="dictate"]').trigger('click')
    FakeRecognition.last!.onerror?.({ error: code })
    FakeRecognition.last!.onend?.()
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toBe(message)
  })
})

describe('altura do campo', () => {
  it('cresce até 40% da coluna e depois rola', async () => {
    const section = document.createElement('section')
    Object.defineProperty(section, 'clientHeight', { value: 500 })
    document.body.appendChild(section)
    vi.stubGlobal('fetch', routeFetch({}))
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' }, attachTo: section })
    const ta = w.find('textarea')
    const el = ta.element as HTMLTextAreaElement
    Object.defineProperty(el, 'scrollHeight', { configurable: true, value: 120 })
    await ta.setValue('a\nb')
    expect(el.style.height).toBe('120px')
    expect(el.style.overflowY).toBe('hidden')
    Object.defineProperty(el, 'scrollHeight', { configurable: true, value: 900 })
    await ta.setValue('muito\ntexto')
    expect(el.style.height).toBe('200px')
    expect(el.style.overflowY).toBe('auto')
    section.remove()
  })
})
