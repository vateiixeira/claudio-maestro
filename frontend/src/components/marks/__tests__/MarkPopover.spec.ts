import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MarkPopover from '../MarkPopover.vue'
import { useSessionsStore } from '../../../stores/sessions'
import { makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let store: ReturnType<typeof useSessionsStore>
beforeEach(() => {
  setActivePinia(createPinia())
  store = useSessionsStore()
})
afterEach(() => {
  document.body.innerHTML = ''
})

const mountPopover = (props: Record<string, unknown> = {}) =>
  mount(MarkPopover, { props: { session: makeSession({ session_id: 's1' }), x: 10, y: 20, ...props }, attachTo: document.body })
const popover = () => document.body.querySelector<HTMLElement>('[data-test="mark-popover"]')!
const press = (target: EventTarget, type: string) => target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }))

describe('popover de marcação', () => {
  it('Esc fecha', () => {
    const w = mountPopover()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })
  it('pointerdown fora fecha', () => {
    const w = mountPopover()
    press(document.body, 'pointerdown')
    expect(w.emitted('close')).toHaveLength(1)
  })
  it('pointerdown dentro não fecha', () => {
    const w = mountPopover()
    press(popover().querySelector('[data-test="mark-review"]')!, 'pointerdown')
    expect(w.emitted('close')).toBeUndefined()
  })
  it('pointerdown em um gatilho ignorado não fecha', () => {
    const trigger = document.createElement('button')
    document.body.appendChild(trigger)
    const w = mountPopover({ ignore: [trigger, null] })
    press(trigger, 'pointerdown')
    expect(w.emitted('close')).toBeUndefined()
  })
  it('Tab num item fecha o menu, em vez de deixá-lo aberto com o foco fora', () => {
    const w = mountPopover()
    const item = popover().querySelector<HTMLElement>('[data-test="mark-monday"]')!
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    item.dispatchEvent(event)
    expect(w.emitted('close')).toHaveLength(1)
    expect(event.defaultPrevented).toBe(true)
  })
  it('Shift+Tab num item também fecha', () => {
    const w = mountPopover()
    popover().querySelector<HTMLElement>('[data-test="mark-review"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })
  it('Tab no campo de data deixa o foco ir ao botão Salvar', async () => {
    const w = mountPopover()
    popover().querySelector<HTMLElement>('[data-test="mark-pick-date"]')!.click()
    await vi.waitFor(() => expect(popover().querySelector('[data-test="mark-date-input"]')).not.toBeNull())
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    popover().querySelector('[data-test="mark-date-input"]')!.dispatchEvent(event)
    expect(w.emitted('close')).toBeUndefined()
    expect(event.defaultPrevented).toBe(false)
  })
  it('o foco saindo do menu por outro caminho também fecha', () => {
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    const w = mountPopover()
    popover().dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: outside }))
    expect(w.emitted('close')).toHaveLength(1)
  })
  it('o foco passando de um item a outro dentro do menu não fecha', () => {
    const w = mountPopover()
    const [a, b] = popover().querySelectorAll('[role^="menuitem"]')
    a!.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: b! }))
    expect(w.emitted('close')).toBeUndefined()
  })
  it('foca o primeiro item ao abrir', () => {
    mountPopover()
    expect(document.activeElement).toBe(popover().querySelector('[data-test="mark-tomorrow"]'))
  })
  it('erro da API aparece em role="alert"', async () => {
    vi.spyOn(store, 'setMark').mockRejectedValue(new Error('falhou'))
    const w = mountPopover()
    await popover().querySelector<HTMLButtonElement>('[data-test="mark-review"]')!.click()
    await vi.waitFor(() => expect(popover().querySelector('[role="alert"]')?.textContent).toContain('falhou'))
    expect(w.emitted('close')).toBeUndefined()
  })
  it('devolve o foco ao elemento de antes ao fechar', () => {
    const before = document.createElement('button')
    document.body.appendChild(before)
    before.focus()
    const w = mountPopover()
    expect(document.activeElement).not.toBe(before)
    w.unmount()
    expect(document.activeElement).toBe(before)
  })
  it('não rouba o foco se ele já foi para outro lugar', () => {
    const before = document.createElement('button')
    const other = document.createElement('input')
    document.body.append(before, other)
    before.focus()
    const w = mountPopover()
    other.focus()
    w.unmount()
    expect(document.activeElement).toBe(other)
  })
  it('limita o topo pela altura real do popover', async () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')!
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 200 })
    try {
      const w = mountPopover({ y: window.innerHeight - 10 })
      await w.vm.$nextTick()
      expect(popover().style.top).toBe(`${window.innerHeight - 200 - 8}px`)
    } finally {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', original)
    }
  })
})
