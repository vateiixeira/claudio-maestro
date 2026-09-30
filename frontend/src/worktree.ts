import type { Session } from './types/api'

/** "worktree <name> · <branch>", "worktree <name>" without a branch, or null outside worktrees. */
export function worktreeLabel(s: Pick<Session, 'worktree_name' | 'git_branch'>): string | null {
  if (!s.worktree_name) return null
  return s.git_branch ? `worktree ${s.worktree_name} · ${s.git_branch}` : `worktree ${s.worktree_name}`
}
