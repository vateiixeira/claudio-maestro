import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { useSmoothText } from '../useSmoothText'

// Manual requestAnimationFrame: each tick(ms) advances the fake clock and runs the queued callbacks.
let queue: Map<number, FrameRequestCallback>
let nextId: number
let now: number
const cancelSpy = vi.fn()

function tick(ms = 1000 / 60) {
  now += ms
  const callbacks = [...queue.values()]
  queue = new Map()
  for (const cb of callbacks) cb(now)
}

async function frames(count: number, ms = 1000 / 60) {
  for (let i = 0; i < count; i++) {
    tick(ms)
    await nextTick()
  }
}

function stubMotion(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduced && query.includes('prefers-reduced-motion'),
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

function harness(state: { text: string, streaming: boolean }) {
  return mount(defineComponent({
    setup() {
      const shown = useSmoothText(() => state.text, () => state.streaming)
      return () => h('p', shown.value)
    },
  }))
}

beforeEach(() => {
  queue = new Map()
  nextId = 1
  now = 0
  cancelSpy.mockClear()
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    const id = nextId++
    queue.set(id, cb)
    return id
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    cancelSpy(id)
    queue.delete(id)
  })
  stubMotion(false)
})
afterEach(() => vi.unstubAllGlobals())

describe('useSmoothText', () => {
  it('sem streaming (histórico, recarga) devolve o texto inteiro na hora, sem quadros', async () => {
    const state = reactive({ text: 'texto longo do histórico', streaming: false })
    const w = harness(state)
    expect(w.text()).toBe('texto longo do histórico')
    expect(queue.size).toBe(0)
    state.text = 'texto longo do histórico, mais um pouco'
    await nextTick()
    expect(w.text()).toBe('texto longo do histórico, mais um pouco')
    expect(queue.size).toBe(0)
  })

  it('o texto que já existe ao montar em streaming aparece inteiro; só o que chega depois é suavizado', async () => {
    const state = reactive({ text: 'abcdef', streaming: true })
    const w = harness(state)
    expect(w.text()).toBe('abcdef')
  })

  it('libera no mínimo 90 caracteres por segundo', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'x'.repeat(30) // atraso de 30: 30 / 0,4 = 75/s, abaixo do mínimo
    await nextTick()
    await frames(1) // o primeiro quadro só marca o relógio
    expect(w.text().length).toBe(0)
    await frames(6) // 0,1 s
    expect(w.text().length).toBeGreaterThanOrEqual(8)
    expect(w.text().length).toBeLessThanOrEqual(10)
    await frames(60) // sobra tempo: chega ao fim
    expect(w.text().length).toBe(30)
  })

  it('acelera com atraso grande: delay / 0,4 caracteres por segundo, bem acima do mínimo', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'z'.repeat(1000)
    await nextTick()
    await frames(1) // marca o relógio
    await frames(1) // um quadro de 1/60 s a 2500/s libera cerca de 41; no mínimo seriam 1,5
    const first = w.text().length
    expect(first).toBeGreaterThanOrEqual(38)
    expect(first).toBeLessThanOrEqual(44)
    await frames(24) // 0,4 s no total: o atraso cai pelo caminho, sem esperar 1000 / 90 s
    expect(w.text().length).toBeGreaterThan(500)
    expect(w.text().length).toBeLessThan(1000)
    await frames(240) // o resto chega bem antes dos ~11 s do ritmo mínimo
    expect(w.text().length).toBe(1000)
    expect(queue.size).toBe(0)
  })

  it('ao terminar o streaming continua liberando até alcançar o texto inteiro, sem pular', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    const full = 'w'.repeat(500)
    state.text = full
    await nextTick()
    await frames(1)
    await frames(2)
    state.streaming = false
    await nextTick()
    const afterEnd = w.text().length
    expect(afterEnd).toBeLessThan(full.length)
    await frames(1)
    expect(w.text().length).toBeLessThan(full.length)
    await frames(240)
    expect(w.text()).toBe(full)
    expect(queue.size).toBe(0)
  })

  it('o texto que chega depois de o streaming acabar volta a ser imediato', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'abc'
    await nextTick()
    await frames(1)
    await frames(30)
    state.streaming = false
    await nextTick()
    await frames(5)
    expect(w.text()).toBe('abc')
    state.text = 'abc def'
    await nextTick()
    expect(w.text()).toBe('abc def')
  })

  it('com prefers-reduced-motion devolve o texto que chegou, sem suavizar', async () => {
    stubMotion(true)
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'chegou tudo de uma vez'
    await nextTick()
    expect(w.text()).toBe('chegou tudo de uma vez')
    expect(queue.size).toBe(0)
  })

  it('não parte um par substituto ao meio', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = '😀'.repeat(50)
    await nextTick()
    for (let i = 0; i < 80; i++) {
      await frames(1, 7)
      const text = w.text()
      expect(text).not.toMatch(/[\uD800-\uDBFF]$/)
    }
  })

  it('texto que encolhe em streaming nunca passa do que chegou', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'x'.repeat(200)
    await nextTick()
    await frames(1)
    await frames(10)
    expect(w.text().length).toBeGreaterThan(10)
    state.text = 'x'.repeat(5)
    await nextTick()
    expect(w.text().length).toBeLessThanOrEqual(5)
    await frames(30)
    expect(w.text()).toBe('xxxxx')
    expect(queue.size).toBe(0) // alcançou: sem quadros até chegar mais texto
    state.streaming = false
    await nextTick()
    expect(w.text()).toBe('xxxxx')
    expect(queue.size).toBe(0)
  })

  it('texto reescrito ao fim do streaming aparece inteiro na hora e para os quadros', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'rascunho '.repeat(50)
    await nextTick()
    await frames(1)
    await frames(5)
    expect(w.text().length).toBeLessThan(state.text.length)
    const rewritten = 'versão final, outro texto. ' + 'z'.repeat(500) // mais longo que o já mostrado
    state.text = rewritten
    state.streaming = false
    await nextTick()
    expect(w.text()).toBe(rewritten)
    expect(queue.size).toBe(0)
    await frames(3)
    expect(w.text()).toBe(rewritten)
  })

  it('texto encolhido depois de o streaming acabar, no meio da alcançada, aparece na hora', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'y'.repeat(300)
    await nextTick()
    await frames(1)
    await frames(5)
    state.streaming = false
    await nextTick()
    state.text = 'y'.repeat(3)
    await nextTick()
    expect(w.text()).toBe('yyy')
    expect(queue.size).toBe(0)
  })

  it('componente reaproveitado com outro texto, sem streaming, mostra o novo na hora', async () => {
    const state = reactive({ text: 'um texto antigo', streaming: false })
    const w = harness(state)
    state.text = 'outro texto, bem diferente'
    await nextTick()
    expect(w.text()).toBe('outro texto, bem diferente')
    expect(queue.size).toBe(0)
  })

  it('devolve o ouvinte de quadro ao desmontar', async () => {
    const state = reactive({ text: '', streaming: true })
    const w = harness(state)
    state.text = 'x'.repeat(100)
    await nextTick()
    expect(queue.size).toBe(1)
    w.unmount()
    expect(queue.size).toBe(0)
    expect(cancelSpy).toHaveBeenCalled()
  })
})
