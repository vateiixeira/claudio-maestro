import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import TextBlock from '../TextBlock.vue'
import ConversationBlock from '../ConversationBlock.vue'
import type { TextItem } from '../../../types/conversation'

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
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { queue.set(id, cb); return id++ })
  vi.stubGlobal('cancelAnimationFrame', (n: number) => { queue.delete(n) })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }))
})
afterEach(() => vi.unstubAllGlobals())

describe('TextBlock avisa que o texto mostrado cresceu', () => {
  it('não avisa ao montar, nem com o histórico', async () => {
    const w = mount(TextBlock, { props: { item: item({ text: 'já estava aqui', streaming: false }) } })
    await nextTick()
    expect(w.emitted('reveal')).toBeUndefined()
  })

  it('avisa a cada passo em que o texto suavizado cresce, e para quando alcança o fim', async () => {
    const w = mount(TextBlock, { props: { item: item() } })
    await w.setProps({ item: item({ text: 'a'.repeat(120) }) })
    await frame()
    await frame()
    const during = w.emitted('reveal')!.length
    expect(during).toBeGreaterThan(0)
    for (let i = 0; i < 60; i++) await frame()
    const done = w.emitted('reveal')!.length
    expect(w.find('.markdown').text()).toContain('a'.repeat(120))
    await frame()
    await frame()
    expect(w.emitted('reveal')).toHaveLength(done)
  })

  it('o aviso sai depois de o DOM mostrar o texto novo', async () => {
    let seen = ''
    const w = mount(TextBlock, { props: { item: item() }, attrs: { onReveal: () => { seen = w.find('.markdown').text() } } })
    await w.setProps({ item: item({ text: 'a'.repeat(120) }) })
    await frame()
    await frame()
    expect(seen.length).toBeGreaterThan(0)
  })

  it('o ConversationBlock repassa o aviso, também o de um filho', async () => {
    const w = mount(ConversationBlock, { props: { item: item({ text: '', streaming: true }) } })
    await w.setProps({ item: item({ text: 'b'.repeat(80) }) })
    await frame()
    await frame()
    expect(w.emitted('reveal')?.length).toBeGreaterThan(0)
  })
})
