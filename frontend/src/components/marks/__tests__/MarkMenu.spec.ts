import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MarkMenu from '../MarkMenu.vue'
import { useSessionsStore } from '../../../stores/sessions'
import { makeSession } from '../../../test/factories'

let store: ReturnType<typeof useSessionsStore>
beforeEach(() => {
  setActivePinia(createPinia())
  store = useSessionsStore()
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 9, 3, 14, 0)) // sábado
})
afterEach(() => vi.useRealTimers())

const mountMenu = (overrides = {}) => mount(MarkMenu, { props: { session: makeSession({ session_id: 's1', ...overrides }) } })

describe('menu de marcação', () => {
  it('Amanhã às 9h marca em espera até amanhã 9h', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    const w = mountMenu()
    await w.find('[data-test="mark-tomorrow"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', 'on_hold', { mark_until: Math.floor(new Date(2026, 9, 4, 9).getTime() / 1000) })
    await vi.waitFor(() => expect(w.emitted('done')).toBeTruthy())
  })
  it('Próxima segunda às 9h', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    await mountMenu().find('[data-test="mark-monday"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', 'on_hold', { mark_until: Math.floor(new Date(2026, 9, 5, 9).getTime() / 1000) })
  })
  it('Sem data marca em espera sem data', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    await mountMenu().find('[data-test="mark-no-date"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', 'on_hold', { mark_until: null })
  })
  it('Escolher data usa o campo e salva', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    const w = mountMenu()
    await w.find('[data-test="mark-pick-date"]').trigger('click')
    await w.find('[data-test="mark-date-input"]').setValue('2026-10-10T08:30')
    await w.find('[data-test="mark-date-save"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', 'on_hold', { mark_until: Math.floor(new Date(2026, 9, 10, 8, 30).getTime() / 1000) })
  })
  it('Bloqueada com nota', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    const w = mountMenu()
    await w.find('[data-test="mark-blocked"]').trigger('click')
    const input = w.find('[data-test="mark-note-input"]')
    expect(input.attributes('maxlength')).toBe('80')
    await input.setValue('esperando CI')
    await input.trigger('keydown', { key: 'Enter' })
    expect(spy).toHaveBeenCalledWith('s1', 'blocked', { mark_note: 'esperando CI' })
  })
  it('Para revisar e Remover marcação', async () => {
    const spy = vi.spyOn(store, 'setMark').mockResolvedValue()
    const w = mountMenu({ mark: 'review' })
    expect(w.find('[data-test="mark-review"]').attributes('aria-checked')).toBe('true')
    await w.find('[data-test="mark-clear"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', null)
  })
  it('Remover marcação não aparece sem marcação', () => {
    expect(mountMenu().find('[data-test="mark-clear"]').exists()).toBe(false)
  })
  it('Prioridade alterna', async () => {
    const spy = vi.spyOn(store, 'setPriority').mockResolvedValue()
    await mountMenu({ priority: true }).find('[data-test="mark-priority"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', false)
  })
  it('erro da API vira evento error', async () => {
    vi.spyOn(store, 'setMark').mockRejectedValue(new Error('falhou'))
    const w = mountMenu()
    await w.find('[data-test="mark-review"]').trigger('click')
    await vi.waitFor(() => expect(w.emitted('error')).toBeTruthy())
  })
  describe('teclado', () => {
    const order = ['mark-tomorrow', 'mark-monday', 'mark-pick-date', 'mark-no-date', 'mark-blocked', 'mark-review', 'mark-priority']
    const mountAttached = () => mount(MarkMenu, { props: { session: makeSession({ session_id: 's1' }) }, attachTo: document.body })
    const focused = () => (document.activeElement as HTMLElement | null)?.getAttribute('data-test')
    afterEach(() => { document.body.innerHTML = '' })

    it('setas movem o foco entre os itens, circulando', async () => {
      const w = mountAttached()
      w.find<HTMLElement>('[data-test="mark-tomorrow"]').element.focus()
      await w.find('[data-test="mark-tomorrow"]').trigger('keydown', { key: 'ArrowDown' })
      expect(focused()).toBe('mark-monday')
      await w.find('[data-test="mark-monday"]').trigger('keydown', { key: 'ArrowUp' })
      expect(focused()).toBe('mark-tomorrow')
      await w.find('[data-test="mark-tomorrow"]').trigger('keydown', { key: 'ArrowUp' })
      expect(focused()).toBe(order[order.length - 1])
      await w.find('[data-test="mark-priority"]').trigger('keydown', { key: 'ArrowDown' })
      expect(focused()).toBe('mark-tomorrow')
    })
    it('Home e End vão ao primeiro e ao último', async () => {
      const w = mountAttached()
      w.find<HTMLElement>('[data-test="mark-review"]').element.focus()
      await w.find('[data-test="mark-review"]').trigger('keydown', { key: 'Home' })
      expect(focused()).toBe('mark-tomorrow')
      await w.find('[data-test="mark-tomorrow"]').trigger('keydown', { key: 'End' })
      expect(focused()).toBe('mark-priority')
    })
    it('o campo de nota não rouba as setas e fica fora do role="menu" solto', async () => {
      const w = mountAttached()
      await w.find('[data-test="mark-blocked"]').trigger('click')
      const input = w.find<HTMLInputElement>('[data-test="mark-note-input"]')
      await input.trigger('keydown', { key: 'ArrowDown' })
      expect(document.activeElement).toBe(input.element)
      expect(input.element.parentElement?.getAttribute('role')).toBe('none')
    })
    it('o campo de data fica num wrapper role="none"', async () => {
      const w = mountAttached()
      await w.find('[data-test="mark-pick-date"]').trigger('click')
      expect(w.find('[data-test="mark-date-input"]').element.parentElement?.getAttribute('role')).toBe('none')
    })
  })
})
