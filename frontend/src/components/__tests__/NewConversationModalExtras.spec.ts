import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { EFFORT_LABELS, MODE_LABELS } from '../../sessionOptions'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import NewConversationModal from '../NewConversationModal.vue'
import { createAppRouter } from '../../router'
import { takePendingDraft } from '../../conversation/pendingDrafts'
import { claimLocalImages, localImagesFor, resetLocalImages } from '../../conversation/localImages'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { jsonResponse, makeProject, makeSession, routeFetch } from '../../test/factories'
import { resetFileReads, settleReads, trackFileReads } from '../../test/fileReader'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b', path: '/b' })]
  projects.loaded = true
})
afterEach(() => {
  vi.unstubAllGlobals()
  resetLocalImages()
  resetFileReads()
})

function handlers(extra = {}) {
  return {
    'GET /api/models': () => jsonResponse([]),
    'POST /api/projects/2/sessions': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }), 201),
    'POST /api/sessions/nova/messages': () => jsonResponse({ state: 'running', external_activity: false }, 202),
    'PATCH /api/sessions/nova': () => jsonResponse(makeSession({ session_id: 'nova', project_id: 2 })),
    ...extra,
  }
}

async function openModal(extra = {}) {
  trackFileReads()
  const fetch = routeFetch(handlers(extra))
  vi.stubGlobal('fetch', fetch)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/inbox')
  useNewConversationStore(pinia).open(2)
  const wrapper = mount(NewConversationModal, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router, fetch }
}
type Wrapper = Awaited<ReturnType<typeof openModal>>['wrapper']

function png(name = 'tela.png', bytes = 3, type = 'image/png') {
  return new File([new Uint8Array(bytes).fill(65)], name, { type })
}
const chips = (w: Wrapper) => w.findAll('[data-test="attachment-draft"]')
async function pickFiles(w: Wrapper, files: File[]) {
  const input = w.find('[data-test="nc-file-input"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
  await settleReads()
}
async function paste(w: Wrapper, files: File[]) {
  await w.find('[data-test="nc-prompt"]').trigger('paste', { clipboardData: { files, items: [] } })
  await settleReads()
}
async function drop(w: Wrapper, files: File[]) {
  await w.trigger('drop', { dataTransfer: { files, types: ['Files'] } })
  await settleReads()
}

describe('modal de nova conversa: imagens', () => {
  it('o botão de anexar abre o seletor e mostra a miniatura, que pode ser removida', async () => {
    const { wrapper } = await openModal()
    const input = wrapper.find('[data-test="nc-file-input"]')
    expect(input.attributes('accept')).toBe('image/png,image/jpeg,image/gif,image/webp')
    expect(input.attributes('multiple')).toBeDefined()
    const click = vi.spyOn(input.element as HTMLInputElement, 'click')
    await wrapper.find('[data-test="nc-attach"]').trigger('click')
    expect(click).toHaveBeenCalled()

    await pickFiles(wrapper, [png('tela.png', 2048)])
    expect(chips(wrapper)).toHaveLength(1)
    expect(chips(wrapper)[0]!.text()).toContain('tela.png')
    expect(chips(wrapper)[0]!.text()).toContain('2 KB')
    expect(chips(wrapper)[0]!.find('img').attributes('src')).toMatch(/^data:image\/png;base64,/)
    await chips(wrapper)[0]!.find('button[aria-label="Remover imagem tela.png"]').trigger('click')
    expect(chips(wrapper)).toHaveLength(0)
  })

  it('colar e soltar arquivo anexam', async () => {
    const { wrapper } = await openModal()
    await paste(wrapper, [png('colada.png')])
    await drop(wrapper, [png('solta.webp', 3, 'image/webp')])
    expect(chips(wrapper).map((c) => c.text())).toEqual([expect.stringContaining('colada.png'), expect.stringContaining('solta.webp')])
  })

  function dragEvent(type: 'dragover' | 'drop', types: string[]) {
    const event = new Event(type, { cancelable: true, bubbles: true })
    Object.defineProperty(event, 'dataTransfer', { value: { types, files: [] } })
    return event
  }

  it('arrastar arquivo sobre o modal não deixa o navegador abri-lo', async () => {
    const { wrapper } = await openModal()
    const over = dragEvent('dragover', ['Files'])
    wrapper.element.dispatchEvent(over)
    expect(over.defaultPrevented).toBe(true)
    const drop = dragEvent('drop', ['Files'])
    wrapper.element.dispatchEvent(drop)
    expect(drop.defaultPrevented).toBe(true)
  })

  it('arrastar texto sobre o modal não é interceptado, para soltar em Prompt e Título', async () => {
    const { wrapper } = await openModal()
    const over = dragEvent('dragover', ['text/plain'])
    wrapper.find('[data-test="nc-prompt"]').element.dispatchEvent(over)
    expect(over.defaultPrevented).toBe(false)
    const drop = dragEvent('drop', ['text/plain'])
    wrapper.find('[data-test="nc-prompt"]').element.dispatchEvent(drop)
    expect(drop.defaultPrevented).toBe(false)
    expect(chips(wrapper)).toHaveLength(0)
  })

  it('avisa que as imagens não ficam guardadas no rascunho, só quando há imagens anexadas', async () => {
    const { wrapper } = await openModal()
    expect(wrapper.find('[data-test="nc-images-note"]').exists()).toBe(false)
    await pickFiles(wrapper, [png('a.png')])
    expect(wrapper.find('[data-test="nc-images-note"]').text()).toContain('não ficam guardadas no rascunho')
    await chips(wrapper)[0]!.find('button[aria-label="Remover imagem a.png"]').trigger('click')
    expect(wrapper.find('[data-test="nc-images-note"]').exists()).toBe(false)
  })

  it('dois anexos ao mesmo tempo nunca passam de 10 imagens', async () => {
    const { wrapper } = await openModal()
    const input = wrapper.find('[data-test="nc-file-input"]')
    for (const batch of [Array.from({ length: 6 }, (_, i) => png(`a${i}.png`)), Array.from({ length: 6 }, (_, i) => png(`b${i}.png`))]) {
      Object.defineProperty(input.element, 'files', { value: batch, configurable: true })
      await input.trigger('change')
    }
    await settleReads()
    expect(chips(wrapper)).toHaveLength(10)
    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('10 imagens')
  })

  it('valida formato, tamanho e quantidade como o compositor', async () => {
    const { wrapper } = await openModal()
    await pickFiles(wrapper, [png('doc.pdf', 3, 'application/pdf')])
    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('doc.pdf')
    await pickFiles(wrapper, [png('grande.png', 5 * 1024 * 1024 + 1)])
    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('5 MB')
    await pickFiles(wrapper, Array.from({ length: 11 }, (_, i) => png(`i${i}.png`)))
    expect(chips(wrapper)).toHaveLength(10)
    expect(wrapper.find('[data-test="nc-error"]').text()).toContain('10 imagens')
  })

  it('envia as imagens em base64 com a primeira mensagem, mesmo sem texto, e guarda as miniaturas', async () => {
    const { wrapper, fetch } = await openModal()
    await pickFiles(wrapper, [png('a.png', 3)])
    expect(wrapper.find('[data-test="nc-submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const send = fetch.mock.calls.find(([url]) => url === '/api/sessions/nova/messages')!
    expect(JSON.parse(send[1]!.body as string)).toEqual({ text: '', images: [{ media_type: 'image/png', data: 'QUFB' }] })
    claimLocalImages('nova', { type: 'user', id: 'u1', text: '', images: [{ type: 'image', media_type: 'image/png', size: 3 }] })
    expect(localImagesFor('u1')).toEqual(['data:image/png;base64,QUFB'])
  })

  it('quando o envio falha, as imagens vão junto para o compositor da conversa', async () => {
    const { wrapper } = await openModal({ 'POST /api/sessions/nova/messages': () => jsonResponse({ detail: 'Sem conexão.' }, 503) })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await pickFiles(wrapper, [png('a.png', 3)])
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    const pending = takePendingDraft('nova')!
    expect(pending.text).toBe('oi')
    expect(pending.error).toBe('Sem conexão.')
    expect(pending.images?.map((i) => i.name)).toEqual(['a.png'])
  })
})

describe('modal de nova conversa: título e opções quando o PATCH falha', () => {
  const patchFails = { 'PATCH /api/sessions/nova': () => jsonResponse({ detail: 'Modelo indisponível.' }, 400) }

  async function fillAndSubmit(extra = {}) {
    const opened = await openModal(extra)
    await opened.wrapper.find('[data-test="nc-title"]').setValue('Login')
    await opened.wrapper.find('[data-test="nc-prompt"]').setValue('Corrija o login')
    await opened.wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    return opened
  }

  it('mantém o modal aberto com título, prompt e erro legível, sem enviar a mensagem', async () => {
    const { wrapper, router, fetch } = await fillAndSubmit(patchFails)
    const error = wrapper.find('[data-test="nc-error"]').text()
    expect(error).toContain('A conversa foi criada')
    expect(error).toContain('título e as opções')
    expect(error).toContain('Modelo indisponível.')
    expect((wrapper.find('[data-test="nc-title"]').element as HTMLInputElement).value).toBe('Login')
    expect((wrapper.find('[data-test="nc-prompt"]').element as HTMLTextAreaElement).value).toBe('Corrija o login')
    expect(useNewConversationStore(pinia).isOpen).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
    expect(fetch.mock.calls.some(([url]) => url === '/api/sessions/nova/messages')).toBe(false)
    expect(localStorage.getItem('maestro:new-conversation')).not.toBeNull()
    expect(wrapper.find('[data-test="nc-submit"]').attributes('disabled')).toBeUndefined()
  })

  it('tentar de novo reaproveita a sessão criada, reaplica o PATCH e envia', async () => {
    let fail = true
    const { wrapper, router, fetch } = await fillAndSubmit({
      'PATCH /api/sessions/nova': () => (fail ? jsonResponse({ detail: 'Modelo indisponível.' }, 400) : jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }))),
    })
    fail = false
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()

    expect(fetch.mock.calls.filter(([url]) => url === '/api/projects/2/sessions')).toHaveLength(1)
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(2)
    expect(fetch.mock.calls.filter(([url]) => url === '/api/sessions/nova/messages')).toHaveLength(1)
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
  })

  it('o que foi editado depois da falha vale na nova tentativa', async () => {
    let fail = true
    const { wrapper, fetch } = await fillAndSubmit({
      'PATCH /api/sessions/nova': () => (fail ? jsonResponse({ detail: 'x' }, 400) : jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }))),
    })
    fail = false
    await wrapper.find('[data-test="nc-title"]').setValue('Outro título')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    const patches = fetch.mock.calls.filter(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(patches[1]![1]!.body as string)).toEqual({ title: 'Outro título' })
  })

  it('depois de criada, a sessão prende o projeto escolhido', async () => {
    const { wrapper } = await fillAndSubmit(patchFails)
    expect((wrapper.find('[data-test="nc-project"]').element as HTMLSelectElement).disabled).toBe(true)
  })

  it('se o PATCH deu certo e o envio falha, abre a conversa sem repetir o PATCH', async () => {
    const { fetch, router } = await fillAndSubmit({ 'POST /api/sessions/nova/messages': () => jsonResponse({ detail: 'Sem conexão.' }, 503) })
    expect(fetch.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(1)
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(takePendingDraft('nova')).toMatchObject({ text: 'Corrija o login', error: 'Sem conexão.' })
  })
})

describe('modal de nova conversa: sessão criada e PATCH falhou', () => {
  const patchFails = { 'PATCH /api/sessions/nova': () => jsonResponse({ detail: 'Modelo indisponível.' }, 400) }

  async function failedPatch() {
    const opened = await openModal(patchFails)
    await opened.wrapper.find('[data-test="nc-title"]').setValue('Login')
    await opened.wrapper.find('[data-test="nc-prompt"]').setValue('Corrija o login')
    await pickFiles(opened.wrapper, [png('a.png', 3)])
    await opened.wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    expect(opened.wrapper.find('[data-test="nc-error"]').text()).toContain('A conversa foi criada')
    return opened
  }

  function expectLeftToCreated({ router, fetch }: Awaited<ReturnType<typeof openModal>>) {
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
    expect(localStorage.getItem('maestro:new-conversation')).toBeNull()
    expect(fetch.mock.calls.filter(([url]) => url === '/api/projects/2/sessions')).toHaveLength(1)
    expect(fetch.mock.calls.some(([url]) => url === '/api/sessions/nova/messages')).toBe(false)
    const pending = takePendingDraft('nova')!
    expect(pending.text).toBe('Corrija o login')
    expect(pending.error).toContain('A conversa foi criada')
    expect(pending.error).toContain('Modelo indisponível.')
    expect(pending.images?.map((i) => i.name)).toEqual(['a.png'])
  }

  it('fechar no × leva à conversa criada com o rascunho no compositor', async () => {
    const opened = await failedPatch()
    await opened.wrapper.find('[data-test="nc-close"]').trigger('click')
    await flushPromises()
    expectLeftToCreated(opened)
  })

  it('Esc leva à conversa criada', async () => {
    const opened = await failedPatch()
    await opened.wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expectLeftToCreated(opened)
  })

  it('clicar no fundo leva à conversa criada', async () => {
    const opened = await failedPatch()
    await opened.wrapper.trigger('click')
    await flushPromises()
    expectLeftToCreated(opened)
  })

  it('descartar leva à conversa criada, sem deixar conversa vazia escondida', async () => {
    const opened = await failedPatch()
    await opened.wrapper.find('[data-test="nc-discard"]').trigger('click')
    await flushPromises()
    expectLeftToCreated(opened)
  })

  it('fechar sem sessão criada continua só fechando', async () => {
    const { wrapper, router } = await openModal()
    await wrapper.find('[data-test="nc-close"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/inbox')
    expect(useNewConversationStore(pinia).isOpen).toBe(false)
  })
})

describe('modal de nova conversa: não fecha durante o envio', () => {
  async function submitting() {
    let release: (r: Response) => void = () => {}
    const opened = await openModal({ 'POST /api/projects/2/sessions': () => new Promise<Response>((resolve) => (release = resolve)) as never })
    await opened.wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await opened.wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    return { ...opened, release: () => release(jsonResponse(makeSession({ session_id: 'nova', project_id: 2 }), 201)) }
  }

  it('Esc, × e clique no fundo não fecham, e descartar fica desabilitado', async () => {
    const { wrapper, release, router } = await submitting()
    const store = useNewConversationStore(pinia)
    await wrapper.find('[data-test="nc-prompt"]').trigger('keydown', { key: 'Escape' })
    await wrapper.find('[data-test="nc-close"]').trigger('click')
    await wrapper.trigger('click')
    expect(store.isOpen).toBe(true)
    expect(wrapper.find('[data-test="nc-discard"]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="nc-discard"]').trigger('click')
    expect(store.isOpen).toBe(true)

    release()
    await flushPromises()
    expect(store.isOpen).toBe(false)
    expect(router.currentRoute.value.fullPath).toBe('/sessions/nova')
  })
})

describe('modal de nova conversa: leituras em andamento', () => {
  it('remover uma imagem durante a leitura de outra mantém a que acabou de ler', async () => {
    const { wrapper } = await openModal()
    await pickFiles(wrapper, [png('a.png')])
    const input = wrapper.find('[data-test="nc-file-input"]')
    Object.defineProperty(input.element, 'files', { value: [png('b.png')], configurable: true })
    await input.trigger('change') // still reading
    await chips(wrapper)[0]!.find('button[aria-label="Remover imagem a.png"]').trigger('click')
    await settleReads()
    expect(chips(wrapper).map((c) => c.text())).toEqual([expect.stringContaining('b.png')])
  })
})

describe('modal de nova conversa: padrões das preferências', () => {
  const prefs = { 'GET /api/state': () => jsonResponse({ preferences: { new_session_model: 'opus', new_session_effort: 'high', new_session_mode: 'acceptEdits' } }) }
  const withModels = { 'GET /api/models': () => jsonResponse([{ value: 'opus', displayName: 'Opus', description: '' }, { value: 'sonnet', displayName: 'Sonnet', description: '' }]) }
  const button = (w: Wrapper, name: string) => w.find(`button[aria-label="${name}"]`)
  async function pick(w: Wrapper, name: string, label: string) {
    await button(w, name).trigger('click')
    await flushPromises()
    const items = new DOMWrapper(document.body).findAll('[role="menuitemradio"]')
    await items.find((i) => i.text().startsWith(label))!.trigger('click')
    await flushPromises()
  }

  it('com o rascunho vazio os botões mostram o valor da preferência', async () => {
    const { wrapper } = await openModal({ ...prefs, ...withModels })
    expect(button(wrapper, 'Modelo').text()).toBe('Opus')
    expect(button(wrapper, 'Raciocínio').text()).toBe(`Raciocínio ${EFFORT_LABELS.high}`)
    expect(button(wrapper, 'Modo').text()).toBe(MODE_LABELS.acceptEdits)
  })

  it('escolher outro modelo mostra o escolhido, e voltar a "Padrão" mostra a preferência', async () => {
    const { wrapper } = await openModal({ ...prefs, ...withModels })
    await pick(wrapper, 'Modelo', 'Sonnet')
    expect(button(wrapper, 'Modelo').text()).toBe('Sonnet')
    await pick(wrapper, 'Modelo', 'Padrão')
    expect(button(wrapper, 'Modelo').text()).toBe('Opus')
  })

  it('sem preferências, ou se a leitura falha, os botões mostram "Padrão"', async () => {
    const { wrapper } = await openModal({ 'GET /api/state': () => jsonResponse({ detail: 'falhou' }, 500) })
    expect(button(wrapper, 'Modelo').text()).toBe('Padrão')
    expect(button(wrapper, 'Raciocínio').text()).toBe('Raciocínio padrão')
    expect(button(wrapper, 'Modo').text()).toBe('Modo padrão')
  })

  it('o envio não manda os valores da preferência: o backend já os aplicou', async () => {
    const { wrapper, fetch } = await openModal({ ...prefs, ...withModels })
    await wrapper.find('[data-test="nc-prompt"]').setValue('oi')
    await wrapper.find('[data-test="nc-submit"]').trigger('click')
    await flushPromises()
    const calls = fetch.mock.calls.map((c) => `${(c[1] as RequestInit | undefined)?.method ?? 'GET'} ${c[0]}`)
    expect(calls).toContain('POST /api/projects/2/sessions')
    expect(calls).not.toContain('PATCH /api/sessions/nova')
  })
})
