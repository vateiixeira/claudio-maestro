import type { Session } from '../types/api'

const inside = (path: string, folder: string) => path === folder || path.startsWith(folder.endsWith('/') ? folder : `${folder}/`)

/**
 * A session running right now in the repository. A session in a worktree only counts for the worktree itself
 * (or a repository inside it), not for the main repository that the worktree hangs from.
 */
export function runningSessionIn(sessions: Session[], repoPath: string): Session | null {
  return sessions.find((s) => {
    if (s.display_state !== 'running') return false
    return s.worktree_path ? inside(repoPath, s.worktree_path) : inside(s.cwd, repoPath)
  }) ?? null
}
