import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TextBlock from '../TextBlock.vue'
import type { TextItem } from '../../../types/conversation'

const renderSpy = vi.hoisted(() => vi.fn())
vi.mock('../../../conversation/markdown', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../conversation/markdown')>()
  return { ...real, renderMarkdown: (text: string) => { renderSpy(text); return real.renderMarkdown(text) } }
})

const item = (over: Partial<TextItem> = {}): TextItem =>
  ({ type: 'text', id: 'x', text: '', streaming: true, parent_tool_use_id: null, ...over }) as TextItem

let queue: Map<number, FrameRequestCallback>
let now: number
async function frame(ms = 1000 / 60) {
  now += ms
  const callbacks = [...queue.values()]
  queue = new Map()
  for (const cb of callbacks) cb(now)
  await nextTick()
}

beforeEach(() => {
  queue = new Map()
  now = 0
  let id = 1
  renderSpy.mockClear()
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { queue.set(id, cb); return id++ })
  vi.stubGlobal('cancelAnimationFrame', (n: number) => { queue.delete(n) })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }))
})
afterEach(() => vi.unstubAllGlobals())

describe('TextBlock em streaming', () => {
  it('mostra o texto aos poucos, não de uma vez', async () => {
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: 'a'.repeat(60) }) })
    await frame()
    await frame()
    const shown = w.find('.markdown').text().length
    expect(shown).toBeGreaterThan(0)
    expect(shown).toBeLessThan(60)
  })

  it('renderiza o markdown no máximo uma vez por quadro', async () => {
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: 'a'.repeat(40) }) })
    await frame()
    renderSpy.mockClear()
    // vários pedaços chegam sem nenhum quadro no meio: nada é renderizado de novo
    await w.setProps({ item: item({ text: 'a'.repeat(50) }) })
    await w.setProps({ item: item({ text: 'a'.repeat(60) }) })
    await w.setProps({ item: item({ text: 'a'.repeat(70) }) })
    expect(renderSpy).not.toHaveBeenCalled()
    await frame()
    expect(renderSpy.mock.calls.length).toBeLessThanOrEqual(1)
  })

  it('mantém o cursor enquanto escreve e some ao terminar', async () => {
    const w = mount(TextBlock, { props: { item: item({ text: 'oi' }) } })
    expect(w.find('[data-test="streaming"]').exists()).toBe(true)
    await w.setProps({ item: item({ text: 'oi', streaming: false }) })
    expect(w.find('[data-test="streaming"]').exists()).toBe(false)
  })

  it('o Copiar copia o texto inteiro que chegou, mesmo com a exibição ainda alcançando', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const full = 'palavra '.repeat(80)
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: full }) })
    await frame()
    await frame()
    await w.setProps({ item: item({ text: full, streaming: false }) })
    expect(w.find('.markdown').text().length).toBeLessThan(full.trim().length)
    await w.find('[data-test="copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(full)
  })

  it('termina mostrando o texto inteiro, sem pular de uma vez ao acabar o streaming', async () => {
    const full = 'palavra '.repeat(80)
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: full }) })
    await frame()
    await frame()
    await w.setProps({ item: item({ text: full, streaming: false }) })
    expect(w.find('.markdown').text().length).toBeLessThan(full.trim().length)
    for (let i = 0; i < 300; i++) await frame()
    expect(w.find('.markdown').text()).toBe(full.trim())
  })

  it('não muda o aria-live: só o aviso de cópia é anunciado', () => {
    const w = mount(TextBlock, { props: { item: item({ text: 'oi', streaming: false }) } })
    expect(w.findAll('[aria-live]').length).toBe(1)
    expect(w.find('[data-test="copy-status"]').attributes('aria-live')).toBe('polite')
  })

  it('libera o ouvinte de quadro ao desmontar', async () => {
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: 'a'.repeat(200) }) })
    expect(queue.size).toBe(1)
    w.unmount()
    expect(queue.size).toBe(0)
  })
})
