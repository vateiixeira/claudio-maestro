import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import LabelPalette from '../LabelPalette.vue'
import { LABEL_PALETTE } from '../../../labelColor'

enableAutoUnmount(afterEach)

describe('LabelPalette', () => {
  it('mostra as sete cores da paleta', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    const colors = wrapper.findAll('[data-test="palette-color"]').map((b) => b.attributes('data-color'))
    expect(colors).toEqual([...LABEL_PALETTE])
    expect(colors).toHaveLength(7)
  })

  it('clicar numa cor emite a cor', async () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    await wrapper.findAll('[data-test="palette-color"]')[3]!.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[LABEL_PALETTE[3]]])
  })

  it('a cor atual tem aria-pressed true e só ela', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[4]!.toUpperCase() } })
    const pressed = wrapper.findAll('[data-test="palette-color"]').map((b) => b.attributes('aria-pressed'))
    expect(pressed).toEqual(['false', 'false', 'false', 'false', 'true', 'false', 'false'])
  })

  it('cada cor tem nome acessível em português', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    const labels = wrapper.findAll('[data-test="palette-color"]').map((b) => b.attributes('aria-label'))
    expect(labels.every((l) => !!l)).toBe(true)
    expect(labels[0]).toBe('Rosa')
  })

  it('"Outra…" abre o seletor e trocar o valor emite o hex escolhido', async () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    const custom = wrapper.get('[data-test="palette-custom"]')
    expect(custom.text()).toBe('Outra…')
    const input = wrapper.get('input[type="color"]')
    let clicked = false
    ;(input.element as HTMLInputElement).click = () => { clicked = true }
    await custom.trigger('click')
    expect(clicked).toBe(true)
    await input.setValue('#123abc')
    expect(wrapper.emitted('update:modelValue')).toEqual([['#123abc']])
  })

  it('uma cor fora da paleta marca "Outra…" como atual', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: '#123abc' } })
    expect(wrapper.get('[data-test="palette-custom"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.findAll('[data-test="palette-color"]').every((b) => b.attributes('aria-pressed') === 'false')).toBe(true)
  })

  it('com cor personalizada, "Outra…" mostra a amostra dessa cor', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: '#123abc' } })
    const swatch = wrapper.get('[data-test="palette-custom-swatch"]')
    expect(swatch.attributes('style')).toMatch(/background-color:\s*(#123abc|rgb\(18, 58, 188\))/i)
    expect(wrapper.get('[data-test="palette-custom"]').attributes('aria-pressed')).toBe('true')
  })

  it('sem cor personalizada, não há amostra', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    expect(wrapper.find('[data-test="palette-custom-swatch"]').exists()).toBe(false)
  })

  it('o input de cor oculto fica com aria-hidden', () => {
    const wrapper = mount(LabelPalette, { props: { modelValue: LABEL_PALETTE[0] } })
    expect(wrapper.get('input[type="color"]').attributes('aria-hidden')).toBe('true')
  })
})
