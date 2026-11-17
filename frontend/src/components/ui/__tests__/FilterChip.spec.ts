import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import FilterChip from '../FilterChip.vue'

enableAutoUnmount(afterEach)

describe('FilterChip', () => {
  it('clicar emite toggle', async () => {
    const wrapper = mount(FilterChip, { props: { label: 'Sua vez' } })
    await wrapper.get('[data-test="filter-chip"]').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })

  it('aria-pressed segue pressed', async () => {
    const wrapper = mount(FilterChip, { props: { label: 'Sua vez' } })
    expect(wrapper.get('[data-test="filter-chip"]').attributes('aria-pressed')).toBe('false')
    await wrapper.setProps({ pressed: true })
    expect(wrapper.get('[data-test="filter-chip"]').attributes('aria-pressed')).toBe('true')
  })

  it('mostra a contagem só quando passada', async () => {
    const wrapper = mount(FilterChip, { props: { label: 'Sua vez' } })
    expect(wrapper.find('[data-test="filter-chip-count"]').exists()).toBe(false)
    await wrapper.setProps({ count: 3 })
    expect(wrapper.get('[data-test="filter-chip-count"]').text()).toBe('3')
    await wrapper.setProps({ count: 0 })
    expect(wrapper.get('[data-test="filter-chip-count"]').text()).toBe('0')
  })

  it('mostra o rótulo e o slot do ícone', () => {
    const wrapper = mount(FilterChip, { props: { label: 'Em execução' }, slots: { icon: '<svg data-test="ic" />' } })
    expect(wrapper.text()).toContain('Em execução')
    expect(wrapper.find('[data-test="ic"]').exists()).toBe(true)
  })
})
