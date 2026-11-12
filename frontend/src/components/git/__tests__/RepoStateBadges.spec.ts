import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RepoStateBadges from '../RepoStateBadges.vue'

describe('estados resumidos do repositório', () => {
  it('expõe alterações e os dois sentidos sem depender da cor', () => {
    const wrapper = mount(RepoStateBadges, { props: { changes: 3, sync: { kind: 'diverged', ahead: 4, behind: 2 } } })
    expect(wrapper.get('[data-test="repo-changes"]').text()).toBe('3 alterações')
    expect(wrapper.get('[data-test="sync-counts"]').attributes('aria-label')).toBe('2 para baixar, 4 para subir')
    expect(wrapper.text()).toContain('2 para baixar')
    expect(wrapper.text()).toContain('4 para enviar')
  })

  it('não mostra contagens zero como ações pendentes', () => {
    const wrapper = mount(RepoStateBadges, { props: { sync: { kind: 'diverged', ahead: 4, behind: 0 } } })
    expect(wrapper.text()).toContain('4 para enviar')
    expect(wrapper.text()).not.toContain('para baixar')
    expect(wrapper.find('[data-test="repo-changes"]').exists()).toBe(false)
  })

  it.each([
    ['synced', 'em dia'], ['none', 'sem upstream'], ['unavailable', 'sincronização indisponível'],
  ] as const)('distingue %s por texto', (kind, text) => {
    const wrapper = mount(RepoStateBadges, { props: { sync: { kind, ahead: 0, behind: 0 } } })
    expect(wrapper.get('[data-test="sync-counts"]').text()).toBe(text)
  })

  it('erro não anuncia o estado como em dia', () => {
    const wrapper = mount(RepoStateBadges, { props: { error: true, sync: { kind: 'synced', ahead: 0, behind: 0 } } })
    expect(wrapper.get('[data-test="repo-state-error"]').text()).toBe('erro')
    expect(wrapper.text()).not.toContain('em dia')
  })
})
