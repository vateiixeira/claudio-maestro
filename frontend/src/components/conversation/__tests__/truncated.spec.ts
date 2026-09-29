import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TruncatedText from '../TruncatedText.vue'
import ConversationBlock from '../ConversationBlock.vue'
import type { ConversationItem } from '../../../types/conversation'

const lines = (n: number) => Array.from({ length: n }, (_, i) => `linha ${i + 1}`).join('\n')
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

function stubClipboard(writeText: (t: string) => Promise<void>) {
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
}

describe('TruncatedText com prévia', () => {
  it('mostra 8 linhas, esmaece e expande com "Ver as N linhas"', async () => {
    const w = mount(TruncatedText, { props: { text: lines(12) } })
    expect(w.text()).toContain('linha 8')
    expect(w.text()).not.toContain('linha 9')
    expect(w.find('[data-test="fade"]').exists()).toBe(true)
    const more = w.find('[data-test="show-lines"]')
    expect(more.text()).toBe('Ver as 12 linhas')
    await more.trigger('click')
    expect(w.text()).toContain('linha 12')
    expect(w.find('[data-test="fade"]').exists()).toBe(false)
    await w.find('[data-test="collapse"]').trigger('click')
    expect(w.text()).not.toContain('linha 9')
  })

  it('texto curto aparece inteiro, sem esmaecimento nem botão', () => {
    const w = mount(TruncatedText, { props: { text: lines(8) } })
    expect(w.text()).toContain('linha 8')
    expect(w.find('[data-test="fade"]').exists()).toBe(false)
    expect(w.find('[data-test="show-lines"]').exists()).toBe(false)
    expect(w.find('[data-test="copy"]').exists()).toBe(true)
  })

  it('expandido mantém o limite de 200 com "Ver tudo"', async () => {
    const w = mount(TruncatedText, { props: { text: lines(250) } })
    await w.find('[data-test="show-lines"]').trigger('click')
    expect(w.text()).toContain('linha 200')
    expect(w.text()).not.toContain('linha 201')
    await w.find('[data-test="show-all"]').trigger('click')
    expect(w.text()).toContain('linha 250')
  })

  it('Copiar copia o texto inteiro e avisa', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn(() => Promise.resolve())
    stubClipboard(writeText)
    const w = mount(TruncatedText, { props: { text: lines(20) } })
    await w.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(lines(20))
    expect(w.find('[data-test="copy"]').text()).toBe('Copiado')
    expect(w.find('[role="status"]').text()).toBe('Copiado')
    vi.advanceTimersByTime(2100)
    await flushPromises()
    expect(w.find('[data-test="copy"]').text()).toBe('Copiar')
  })

  it('avisa quando a cópia falha', async () => {
    stubClipboard(() => Promise.reject(new Error('negado')))
    const w = mount(TruncatedText, { props: { text: 'x' } })
    await w.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(w.find('[role="status"]').text()).toBe('Não foi possível copiar')
  })

  it('a região de status existe antes de copiar', () => {
    const w = mount(TruncatedText, { props: { text: 'x' } })
    expect(w.find('[role="status"]').exists()).toBe(true)
    expect(w.find('[role="status"]').text()).toBe('')
  })

  it('variante de erro usa as cores de erro', () => {
    const w = mount(TruncatedText, { props: { text: lines(12), variant: 'error' } })
    expect(w.find('[data-test="output-box"]').classes()).toContain('bg-diff-del-bg')
    expect(w.find('[data-test="output-box"]').classes()).not.toContain('bg-bg')
    expect(w.find('[data-test="fade"]').classes()).toContain('to-diff-del-bg')
  })

  it('o slot continua recebendo o texto visível', () => {
    const w = mount(TruncatedText, { props: { text: lines(10) }, slots: { default: '<template #default="{ text }"><i>{{ text.split("\\n").length }}</i></template>' } })
    expect(w.find('i').text()).toBe('8')
  })
})

describe('BashTool com prévia', () => {
  const bash = (result: unknown): ConversationItem =>
    ({ type: 'tool', id: 't', tool_use_id: 'tu', name: 'Bash', input: { command: 'ls' }, result, streaming: false, parent_tool_use_id: null }) as ConversationItem

  it('mostra a prévia sem clique e sem botão de saída', () => {
    const w = mount(ConversationBlock, { props: { item: bash({ content: lines(12), is_error: false, details: null }), sessionActive: false } })
    expect(w.text()).toContain('$ ls')
    expect(w.find('[data-test="tool-output"]').text()).toContain('linha 8')
    expect(w.text()).not.toContain('linha 9')
    expect(w.find('[data-test="toggle-output"]').exists()).toBe(false)
    expect(w.text()).toContain('Ver as 12 linhas')
  })

  it('erro também aparece em prévia', () => {
    const w = mount(ConversationBlock, { props: { item: bash({ content: 'falhou', is_error: true, details: null }), sessionActive: false } })
    expect(w.find('[data-test="tool-error"]').text()).toContain('falhou')
    expect(w.find('[data-test="tool-error"] [data-test="output-box"]').classes()).toContain('bg-diff-del-bg')
  })

  it('rodando não tem prévia', () => {
    const w = mount(ConversationBlock, { props: { item: bash(null), sessionActive: true } })
    expect(w.find('[data-test="tool-output"]').exists()).toBe(false)
  })
})
