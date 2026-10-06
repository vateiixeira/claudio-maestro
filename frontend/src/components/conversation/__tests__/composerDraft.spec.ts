import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MessageComposer from '../MessageComposer.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'
import { setPendingDraft } from '../../../conversation/pendingDrafts'
import { resetComposerDrafts } from '../../../conversation/composerDrafts'
import { resetFileReads, settleReads, trackFileReads } from '../../../test/fileReader'

enableAutoUnmount(afterEach)
beforeEach(() => {
  resetComposerDrafts()
  trackFileReads()
})
afterEach(() => {
  vi.unstubAllGlobals()
  resetFileReads()
})

function setup(sessionId = 's1', status = 202) {
  const fetchMock = routeFetch({
    [`POST /api/sessions/${sessionId}/messages`]: () => jsonResponse({}, status),
  })
  vi.stubGlobal('fetch', fetchMock)
  const w = mount(MessageComposer, { props: { sessionId, state: 'idle' } })
  return { w, ta: w.find('textarea'), value: () => (w.find('textarea').element as HTMLTextAreaElement).value }
}

function png(name = 'tela.png') {
  return new File([new Uint8Array(3).fill(65)], name, { type: 'image/png' })
}
async function paste(ta: ReturnType<typeof setup>['ta'], files: File[]) {
  await ta.trigger('paste', { clipboardData: { files, items: files.map((f) => ({ kind: 'file', type: f.type, getAsFile: () => f })) } })
  await settleReads()
}

describe('rascunho por sessão', () => {
  it('o texto volta ao montar outro campo da mesma sessão', async () => {
    const a = setup()
    await a.ta.setValue('metade da frase')
    a.w.unmount()
    const b = setup()
    expect(b.value()).toBe('metade da frase')
  })

  it('persiste no localStorage (sobrevive a recarregar a página)', async () => {
    const a = setup()
    await a.ta.setValue('guardado')
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('guardado')
  })

  it('sessões diferentes não se misturam', async () => {
    const a = setup('s1')
    await a.ta.setValue('da um')
    a.w.unmount()
    const b = setup('s2')
    expect(b.value()).toBe('')
    await b.ta.setValue('da dois')
    b.w.unmount()
    expect(setup('s1').value()).toBe('da um')
    expect(setup('s2').value()).toBe('da dois')
  })

  it('apagar o texto remove o rascunho', async () => {
    const a = setup()
    await a.ta.setValue('x')
    await a.ta.setValue('')
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBeNull()
  })

  it('envio bem-sucedido limpa o rascunho', async () => {
    const a = setup()
    await a.ta.setValue('olá')
    await a.ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBeNull()
    a.w.unmount()
    expect(setup().value()).toBe('')
  })

  it('envio com erro mantém o rascunho', async () => {
    const a = setup('s1', 500)
    await a.ta.setValue('olá')
    await a.ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(a.value()).toBe('olá')
    a.w.unmount()
    expect(setup('s1', 500).value()).toBe('olá')
  })

  it('o que foi digitado durante o envio fica salvo', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    vi.stubGlobal(
      'fetch',
      routeFetch({ 'POST /api/sessions/s1/messages': async () => (await gate, jsonResponse({}, 202)) }),
    )
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
    const ta = w.find('textarea')
    await ta.setValue('primeira')
    await ta.trigger('keydown', { key: 'Enter' })
    await ta.setValue('primeira e mais')
    release()
    await flushPromises()
    expect((ta.element as HTMLTextAreaElement).value).toBe('primeira e mais')
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('primeira e mais')
  })

  it('o primeiro prompt que falhou tem prioridade sobre o rascunho salvo', async () => {
    localStorage.setItem('maestro:composer-draft:s1', 'antigo')
    setPendingDraft('s1', { text: 'prompt que falhou', error: 'falhou' })
    const a = setup()
    expect(a.value()).toBe('prompt que falhou')
    await flushPromises()
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('prompt que falhou')
  })

  it('as imagens anexadas sobrevivem a remontar, mas não vão para o localStorage', async () => {
    const a = setup()
    await paste(a.ta, [png('a.png')])
    expect(a.w.findAll('[data-test="attachment-draft"]')).toHaveLength(1)
    expect(localStorage.length).toBe(0)
    a.w.unmount()
    const b = setup()
    const chips = b.w.findAll('[data-test="attachment-draft"]')
    expect(chips).toHaveLength(1)
    expect(chips[0]!.text()).toContain('a.png')
    expect(setup('s2').w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('remover a imagem também a tira do rascunho', async () => {
    const a = setup()
    await paste(a.ta, [png('a.png')])
    await a.w.find('button[aria-label="Remover imagem a.png"]').trigger('click')
    a.w.unmount()
    expect(setup().w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('enviar as imagens as tira do rascunho', async () => {
    const a = setup()
    await paste(a.ta, [png('a.png')])
    await a.ta.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    a.w.unmount()
    expect(setup().w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('trocar de sessão com o envio pendente: ao responder, o rascunho (texto e imagens) some', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    vi.stubGlobal(
      'fetch',
      routeFetch({ 'POST /api/sessions/s1/messages': async () => (await gate, jsonResponse({}, 202)) }),
    )
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
    const ta = w.find('textarea')
    await ta.setValue('já enviada')
    await paste(ta, [png('a.png')])
    await ta.trigger('keydown', { key: 'Enter' })
    w.unmount()
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('já enviada')
    release()
    await flushPromises()
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBeNull()
    const again = setup()
    expect(again.value()).toBe('')
    expect(again.w.find('[data-test="attachment-draft"]').exists()).toBe(false)
  })

  it('envio com erro depois de desmontar mantém o rascunho', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    vi.stubGlobal(
      'fetch',
      routeFetch({ 'POST /api/sessions/s1/messages': async () => (await gate, jsonResponse({}, 500)) }),
    )
    const w = mount(MessageComposer, { props: { sessionId: 's1', state: 'idle' } })
    await w.find('textarea').setValue('vai falhar')
    await w.find('textarea').trigger('keydown', { key: 'Enter' })
    w.unmount()
    release()
    await flushPromises()
    expect(localStorage.getItem('maestro:composer-draft:s1')).toBe('vai falhar')
  })
})
