import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TextBlock from '../TextBlock.vue'
import type { TextItem } from '../../../types/conversation'

const item = (over: Partial<TextItem> = {}): TextItem =>
  ({ type: 'text', id: 'x', text: '**forte** e `codigo`', streaming: false, parent_tool_use_id: null, ...over }) as TextItem

function setClipboard(writeText: (t: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

describe('copiar resposta', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('copia o markdown bruto e mostra "Copiado" por um instante', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const w = mount(TextBlock, { props: { item: item() } })
    const btn = w.find('[data-test="copy"]')
    expect(btn.attributes('aria-label')).toBe('Copiar resposta')
    await btn.trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('**forte** e `codigo`')
    expect(w.find('[data-test="copy-status"]').text()).toBe('Copiado')
    vi.advanceTimersByTime(1600)
    await w.vm.$nextTick()
    expect(w.find('[data-test="copy-status"]').text()).toBe('')
  })

  it('avisa quando o clipboard falha', async () => {
    setClipboard(vi.fn().mockRejectedValue(new Error('no')))
    const w = mount(TextBlock, { props: { item: item() } })
    await w.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="copy-status"]').text()).toBe('Não foi possível copiar')
  })

  it('o botão escondido não recebe toque e aparece no hover, no foco e em telas sem hover', () => {
    const classes = mount(TextBlock, { props: { item: item() } }).find('[data-test="copy"]').classes()
    expect(classes).toContain('opacity-0')
    expect(classes).toContain('pointer-events-none')
    expect(classes).toContain('group-hover/text:pointer-events-auto')
    expect(classes).toContain('focus-visible:pointer-events-auto')
    expect(classes).toContain('group-focus-within/text:opacity-100')
    expect(classes).toContain('group-focus-within/text:pointer-events-auto')
    expect(classes).toContain('[@media(hover:none)]:opacity-100')
    expect(classes).toContain('[@media(hover:none)]:pointer-events-auto')
  })

  it('não aparece durante o streaming', () => {
    const w = mount(TextBlock, { props: { item: item({ streaming: true }) } })
    expect(w.find('[data-test="copy"]').exists()).toBe(false)
  })
})

describe('copiar bloco de código', () => {
  it('copia só o código do bloco, não a resposta inteira', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)
    const text = 'Veja:\n\n```py\nx = 1\n```\n\nfim'
    const w = mount(TextBlock, { props: { item: item({ text }) } })
    await w.find('[data-code-copy]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('x = 1\n')
    expect(w.find('[data-code-copy]').text()).toBe('Copiado')
  })
})
