import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GroupTag from '../GroupTag.vue'
import { useGroupsStore } from '../../../stores/groups'
import { makeGroup } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => { pinia = createPinia(); setActivePinia(pinia) })

describe('etiqueta do agrupador', () => {
  it('mostra o nome do agrupador conhecido', () => {
    useGroupsStore().groups = [makeGroup({ id: 2, name: 'Checkout' })]
    const w = mount(GroupTag, { props: { groupId: 2 }, global: { plugins: [pinia] } })
    expect(w.find('[data-test="group-tag"]').text()).toContain('Checkout')
    expect(w.find('[data-test="group-tag"]').attributes('title')).toBe('Agrupador: Checkout')
  })

  it('não mostra nada sem agrupador ou com agrupador desconhecido', () => {
    expect(mount(GroupTag, { props: { groupId: null }, global: { plugins: [pinia] } }).find('[data-test="group-tag"]').exists()).toBe(false)
    expect(mount(GroupTag, { props: { groupId: 99 }, global: { plugins: [pinia] } }).find('[data-test="group-tag"]').exists()).toBe(false)
  })
})
