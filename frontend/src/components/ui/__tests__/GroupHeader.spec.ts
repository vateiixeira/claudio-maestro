import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import GroupHeader from '../GroupHeader.vue'

enableAutoUnmount(afterEach)

describe('GroupHeader', () => {
  it('mostra o título e a contagem', () => {
    const wrapper = mount(GroupHeader, { props: { title: 'Sem uso', count: 3 } })
    const root = wrapper.get('[data-test="group-header"]')
    expect(root.text()).toContain('Sem uso')
    expect(wrapper.get('[data-test="group-header-count"]').text()).toBe('3')
  })

  it('sem count, não mostra número', () => {
    const wrapper = mount(GroupHeader, { props: { title: 'Sem uso' } })
    expect(wrapper.find('[data-test="group-header-count"]').exists()).toBe(false)
  })

  it('mostra o slot à direita', () => {
    const wrapper = mount(GroupHeader, { props: { title: 'Sem uso' }, slots: { default: '<button data-test="act">Apagar</button>' } })
    expect(wrapper.get('[data-test="act"]').text()).toBe('Apagar')
  })
})
