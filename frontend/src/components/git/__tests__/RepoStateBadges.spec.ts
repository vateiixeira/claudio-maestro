import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RepoStateBadges from '../RepoStateBadges.vue'
import type { SyncKind } from '../../../git/repoLabel'

type Props = { sync: { kind: SyncKind; ahead: number; behind: number }; changes?: number; error?: boolean }

describe('estados resumidos do repositório', () => {
  it('expõe alterações e os dois sentidos sem depender da cor', () => {
    const wrapper = mount(RepoStateBadges, { props: { changes: 3, sync: { kind: 'diverged', ahead: 4, behind: 2 } } })
    expect(wrapper.get('[data-test="repo-changes"]').text()).toBe('3 alterações')
    expect(wrapper.get('[data-test="sync-counts"]').attributes('aria-label')).toBe('2 para baixar, 4 para subir')
    expect(wrapper.get('[data-test="sync-behind"]').text()).toBe('2 para baixar')
    expect(wrapper.get('[data-test="sync-ahead"]').text()).toBe('4 para enviar')
  })

  it('mostra a situação como texto, sem fundo de selo', () => {
    const cases: Props[] = [
      { changes: 3, sync: { kind: 'diverged' as const, ahead: 4, behind: 2 } },
      { sync: { kind: 'synced' as const, ahead: 0, behind: 0 } },
      { sync: { kind: 'none' as const, ahead: 0, behind: 0 } },
      { sync: { kind: 'unavailable' as const, ahead: 0, behind: 0 } },
      { error: true, sync: { kind: 'synced' as const, ahead: 0, behind: 0 } },
    ]
    for (const props of cases) {
      const wrapper = mount(RepoStateBadges, { props })
      expect(wrapper.html()).not.toMatch(/class="([^"]*\s)?bg-/)
    }
  })

  it('alterações em texto neutro, singular com uma', () => {
    const many = mount(RepoStateBadges, { props: { changes: 3, sync: { kind: 'synced', ahead: 0, behind: 0 } } })
    expect(many.get('[data-test="repo-changes"]').text()).toBe('3 alterações')
    expect(many.get('[data-test="repo-changes"]').classes()).toContain('text-fg-muted')
    const one = mount(RepoStateBadges, { props: { changes: 1, sync: { kind: 'synced', ahead: 0, behind: 0 } } })
    expect(one.get('[data-test="repo-changes"]').text()).toBe('1 alteração')
  })

  it('cores do texto: enviar em laranja, baixar em azul', () => {
    const wrapper = mount(RepoStateBadges, { props: { sync: { kind: 'diverged', ahead: 4, behind: 2 } } })
    expect(wrapper.get('[data-test="sync-ahead"]').classes()).toContain('text-secondary-soft')
    expect(wrapper.get('[data-test="sync-behind"]').classes()).toContain('text-info-soft')
  })

  it('não mostra contagens zero como ações pendentes', () => {
    const wrapper = mount(RepoStateBadges, { props: { sync: { kind: 'diverged', ahead: 4, behind: 0 } } })
    expect(wrapper.text()).toContain('4 para enviar')
    expect(wrapper.text()).not.toContain('para baixar')
    expect(wrapper.find('[data-test="repo-changes"]').exists()).toBe(false)
  })

  it.each([
    ['synced', 'em dia', 'text-fg-muted'],
    ['none', 'sem upstream', 'text-secondary-soft'],
    ['unavailable', 'sincronização indisponível', 'text-secondary-soft'],
  ] as const)('distingue %s por texto', (kind, text, cls) => {
    const wrapper = mount(RepoStateBadges, { props: { sync: { kind, ahead: 0, behind: 0 } } })
    expect(wrapper.get('[data-test="sync-state"]').text()).toBe(text)
    expect(wrapper.get('[data-test="sync-state"]').classes()).toContain(cls)
    expect(wrapper.get('[data-test="sync-counts"]').text()).toBe(text)
  })

  it('erro não anuncia o estado como em dia', () => {
    const wrapper = mount(RepoStateBadges, { props: { error: true, sync: { kind: 'synced', ahead: 0, behind: 0 } } })
    const err = wrapper.get('[data-test="repo-state-error"]')
    expect(err.text()).toBe('erro')
    expect(err.classes()).toContain('text-diff-del-fg')
    expect(wrapper.text()).not.toContain('em dia')
  })
})
