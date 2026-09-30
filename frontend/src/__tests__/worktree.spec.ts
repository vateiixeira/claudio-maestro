import { describe, expect, it } from 'vitest'
import { worktreeLabel } from '../worktree'

describe('worktreeLabel', () => {
  it('nome e branch, só nome, ou nada', () => {
    expect(worktreeLabel({ worktree_name: 'a', git_branch: 'feat/x' })).toBe('worktree a · feat/x')
    expect(worktreeLabel({ worktree_name: 'a', git_branch: null })).toBe('worktree a')
    expect(worktreeLabel({ worktree_name: null, git_branch: 'main' })).toBeNull()
    expect(worktreeLabel({})).toBeNull()
  })
})
