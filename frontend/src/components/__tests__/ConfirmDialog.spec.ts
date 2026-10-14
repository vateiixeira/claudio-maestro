import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ConfirmDialog from '../ConfirmDialog.vue'

enableAutoUnmount(afterEach)

describe('ConfirmDialog', () => {
  it('foca em Cancelar, confirma e cancela', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: 'Descartar alterações?', confirmLabel: 'Descartar', tone: 'danger' }, slots: { default: '<p>Texto</p>' }, attachTo: document.body })
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-test')).toBe('confirm-cancel')
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.text()).toContain('Texto')
    await wrapper.get('[data-test="confirm-ok"]').trigger('click')
    await wrapper.get('[data-test="confirm-cancel"]').trigger('click')
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(2)
  })

  it('Esc fecha mesmo com o foco no body, depois de clicar no texto', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: 'T', confirmLabel: 'Ok' }, slots: { default: '<p data-test="texto">Texto</p>' }, attachTo: document.body })
    await flushPromises()
    await wrapper.get('[data-test="texto"]').trigger('mousedown')
    ;(document.activeElement as HTMLElement | null)?.blur()
    expect(document.activeElement).toBe(document.body)
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('Tab prende o foco: do último botão volta ao primeiro, e do body entra no diálogo', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: 'T', confirmLabel: 'Ok' }, attachTo: document.body })
    await flushPromises()
    const cancel = wrapper.get<HTMLButtonElement>('[data-test="confirm-cancel"]').element
    const ok = wrapper.get<HTMLButtonElement>('[data-test="confirm-ok"]').element
    ok.focus()
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(cancel)
    cancel.focus()
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(ok)
    ;(document.activeElement as HTMLElement).blur()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(cancel)
  })

  it('depois de desmontar, o Esc não faz mais nada', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: 'T', confirmLabel: 'Ok' }, attachTo: document.body })
    await flushPromises()
    wrapper.unmount()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('cancel')).toBeUndefined()
  })

  it('sem autofocus não foca e o confirmar pode ficar desligado', async () => {
    const wrapper = mount(ConfirmDialog, { props: { title: 'T', confirmLabel: 'Ok', confirmDisabled: true, autofocus: false }, attachTo: document.body })
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-test')).not.toBe('confirm-cancel')
    expect(wrapper.get('[data-test="confirm-ok"]').attributes('disabled')).toBeDefined()
  })
})
