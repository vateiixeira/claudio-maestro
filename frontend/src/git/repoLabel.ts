import type { GitRepo } from '../types/api'

/** Name shown for a repository: the project's name for the project folder itself. */
export function repoLabel(repo: Pick<GitRepo, 'rel_path'>, projectName: string | null | undefined): string {
  return repo.rel_path === '.' ? (projectName ?? '.') : repo.rel_path
}

export type SyncKind = 'none' | 'unavailable' | 'synced' | 'diverged'

/** Ahead/behind of the upstream, as of the last fetch. */
export function syncCounts(repo: Pick<GitRepo, 'upstream' | 'ahead' | 'behind'>): { kind: SyncKind; ahead: number; behind: number } {
  if (repo.upstream == null) return { kind: 'none', ahead: 0, behind: 0 }
  if (repo.ahead == null || repo.behind == null) return { kind: 'unavailable', ahead: 0, behind: 0 }
  const kind = repo.ahead === 0 && repo.behind === 0 ? 'synced' : 'diverged'
  return { kind, ahead: repo.ahead, behind: repo.behind }
}
