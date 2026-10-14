import type { Session } from '../types/api'

const inside = (path: string, folder: string) => path === folder || path.startsWith(folder.endsWith('/') ? folder : `${folder}/`)

/**
 * A session running right now in the repository: opened inside it, or in a folder above it (the project root,
 * where "Pedir ao Claude para resolver" opens its session), since from there it can edit the repository too.
 * A session inside the repository wins. A session in a worktree only counts for the worktree itself (or a
 * repository inside it), not for the main repository that the worktree hangs from.
 */
export function runningSessionIn(sessions: Session[], repoPath: string): Session | null {
  const running = sessions.filter((s) => s.display_state === 'running')
  const within = running.find((s) => (s.worktree_path ? inside(repoPath, s.worktree_path) : inside(s.cwd, repoPath)))
  return within ?? running.find((s) => !s.worktree_path && inside(repoPath, s.cwd)) ?? null
}
