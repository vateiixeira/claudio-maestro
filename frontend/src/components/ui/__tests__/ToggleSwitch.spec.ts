import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ToggleSwitch from '../ToggleSwitch.vue'

enableAutoUnmount(afterEach)

const mountSwitch = (props: Record<string, unknown> = {}, attrs: Record<string, unknown> = {}) =>
  mount(ToggleSwitch, { props: { modelValue: false, label: 'Tocar som', ...props }, attrs })

describe('ToggleSwitch', () => {
  it('expõe role switch, aria-checked e o nome', async () => {
    const wrapper = mountSwitch()
    const button = wrapper.get('button')
    expect(button.attributes('role')).toBe('switch')
    expect(button.attributes('aria-label')).toBe('Tocar som')
    expect(button.attributes('aria-checked')).toBe('false')
    await wrapper.setProps({ modelValue: true })
    expect(button.attributes('aria-checked')).toBe('true')
  })

  it('clicar emite o valor invertido', async () => {
    const wrapper = mountSwitch({ modelValue: false })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[true]])
    await wrapper.setProps({ modelValue: true })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual([false])
  })

  it('a tecla Espaço emite o valor invertido, uma vez só', async () => {
    const wrapper = mountSwitch({ modelValue: true })
    await wrapper.get('button').trigger('keydown', { key: ' ' })
    await wrapper.get('button').trigger('keyup', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('Espaço solto sobre o botão sem ter sido pressionado nele não alterna', async () => {
    const wrapper = mountSwitch()
    await wrapper.get('button').trigger('keyup', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    // pressionou, saiu do botão (blur) e soltou de volta: também não alterna
    await wrapper.get('button').trigger('keydown', { key: ' ' })
    await wrapper.get('button').trigger('blur')
    await wrapper.get('button').trigger('keyup', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('a trilha desligada tem contorno visível (fg-subtle)', () => {
    expect(mountSwitch({ modelValue: false }).get('button').classes()).toContain('border-fg-subtle')
  })

  it('desligado não emite', async () => {
    const wrapper = mountSwitch({ disabled: true })
    await wrapper.get('button').trigger('click')
    await wrapper.get('button').trigger('keyup', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('o data-test e o id do pai prevalecem no botão', () => {
    const wrapper = mountSwitch({}, { 'data-test': 'sound-switch', id: 'sound' })
    const button = wrapper.get('button')
    expect(button.attributes('data-test')).toBe('sound-switch')
    expect(button.attributes('id')).toBe('sound')
  })

  it('tem data-test padrão', () => {
    expect(mountSwitch().get('button').attributes('data-test')).toBe('toggle-switch')
  })
})
