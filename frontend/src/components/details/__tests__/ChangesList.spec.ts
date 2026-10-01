import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ChangesList from '../ChangesList.vue'
import type { ChangedFile, ChangesGroup } from '../../../types/api'

enableAutoUnmount(afterEach)

const file = (rel_path: string): ChangedFile => ({
  path: `/home/vi/dev/loja/${rel_path}`, rel_path, added: 1, removed: 0, uncommitted: true,
})
const group = (overrides: Partial<ChangesGroup> = {}): ChangesGroup => ({
  path: '/home/vi/dev/loja', rel_path: '.', branch: 'main', detached: false, head: 'abc', files: [file('a.py')], ...overrides,
})

function mountList(groups: ChangesGroup[]) {
  return mount(ChangesList, { props: { groups, loading: false, error: null, selected: null } })
}

describe('lista de alterações por repositório', () => {
  it('sem worktree mostra o rel_path e o branch, sem rótulo de worktree', () => {
    const w = mountList([group({ rel_path: 'apps/api', path: '/home/vi/dev/loja/apps/api' })])
    expect(w.text()).toContain('apps/api')
    expect(w.text()).toContain('main')
    expect(w.find('[data-test="group-worktree"]').exists()).toBe(false)
    expect(w.find('[data-test="group-header"]').attributes('title')).toBeUndefined()
  })

  it('worktree = null também não mostra o rótulo', () => {
    const w = mountList([group({ worktree: null })])
    expect(w.find('[data-test="group-worktree"]').exists()).toBe(false)
  })

  it('worktree fora do projeto mostra o nome e o branch, não o caminho absoluto, e o caminho vai no title', () => {
    const abs = '/home/vi/worktrees/feat-x'
    const w = mountList([group({ path: abs, rel_path: abs, branch: 'feat-x-branch', worktree: 'feat-x' })])
    const header = w.find('[data-test="group-header"]')
    expect(header.attributes('title')).toBe(abs)
    expect(w.find('[data-test="group-worktree"]').text()).toBe('feat-x')
    expect(header.text()).toContain('feat-x-branch')
    expect(header.text()).not.toContain('/home/vi/worktrees')
  })

  it('worktree dentro do projeto também mostra o nome', () => {
    const w = mountList([group({ path: '/home/vi/dev/loja/.claude/worktrees/x', rel_path: '.claude/worktrees/x', worktree: 'x' })])
    expect(w.find('[data-test="group-worktree"]').text()).toBe('x')
    expect(w.find('[data-test="group-header"]').text()).not.toContain('.claude/worktrees')
  })
})
