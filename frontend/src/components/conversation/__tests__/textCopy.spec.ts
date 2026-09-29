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

  it('não aparece durante o streaming', () => {
    const w = mount(TextBlock, { props: { item: item({ streaming: true }) } })
    expect(w.find('[data-test="copy"]').exists()).toBe(false)
  })
})
