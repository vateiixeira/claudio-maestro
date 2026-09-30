import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DisplayStateIcon from '../DisplayStateIcon.vue'

describe('DisplayStateIcon', () => {
  it('renders running as a spinning arc that respects reduced motion', () => {
    const wrapper = mount(DisplayStateIcon, { props: { display: 'running' } })
    expect(wrapper.attributes('data-shape')).toBe('spinner')
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)
    expect(svg.classes()).toContain('motion-safe:animate-spin')
    expect(svg.classes()).not.toContain('animate-spin')
    expect(wrapper.find('.rounded-full').exists()).toBe(false)
  })

  it('draws the running arc in the primary color', () => {
    const wrapper = mount(DisplayStateIcon, { props: { display: 'running' } })
    expect(wrapper.html()).toContain('stroke-primary')
  })

  it('scales the spinner with the size prop', () => {
    const wrapper = mount(DisplayStateIcon, { props: { display: 'running', size: 20 } })
    const svg = wrapper.find('svg')
    expect(svg.attributes('width')).toBe('20')
    expect(svg.attributes('height')).toBe('20')
  })

  it.each([
    ['waiting', 'triangle'],
    ['finished', 'check'],
  ] as const)('renders %s as %s without spinning', (display, shape) => {
    const wrapper = mount(DisplayStateIcon, { props: { display } })
    expect(wrapper.attributes('data-shape')).toBe(shape)
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('animate-spin')
  })
})
