import { formatActivity } from './format'
import type { GitRepo } from './types/api'

type SyncFields = Pick<GitRepo, 'upstream' | 'ahead' | 'behind' | 'fetched_at'>

/** "1 commit" / "3 commits". */
export function commitsText(count: number): string {
  return count === 1 ? '1 commit' : `${count} commits`
}

/** Commits to pull; zero without upstream or when it is unknown. */
export function behindCount(repo: Pick<GitRepo, 'upstream' | 'behind'>): number {
  return repo.upstream && repo.behind ? repo.behind : 0
}

/** "há 2 min", or null when the repository was never fetched (or the backend does not say). */
export function checkedAgoText(repo: Pick<GitRepo, 'fetched_at'>, nowMs: number): string | null {
  return typeof repo.fetched_at === 'number' ? formatActivity(repo.fetched_at, new Date(nowMs)) : null
}

/** "última vez há 40 min" for a failed check; null when it never succeeded. */
export function lastSuccessText(repo: Pick<GitRepo, 'fetched_at'>, nowMs: number): string | null {
  const ago = checkedAgoText(repo, nowMs)
  return ago ? `última vez ${ago}` : null
}

/** Tooltip of the "to pull" arrow: "3 commits para baixar de origin/main · verificado há 2 min". */
export function behindTitle(repo: SyncFields, nowMs: number): string {
  const base = `${commitsText(behindCount(repo))} para baixar${repo.upstream ? ` de ${repo.upstream}` : ''}`
  const ago = checkedAgoText(repo, nowMs)
  return ago ? `${base} · verificado ${ago}` : base
}

/** Screen reader text of the arrow: "3 commits para baixar". */
export function behindSrText(repo: Pick<GitRepo, 'upstream' | 'behind'>): string {
  return `${commitsText(behindCount(repo))} para baixar`
}

export type SyncState =
  | { kind: 'no-upstream' }
  | { kind: 'fetching' }
  | { kind: 'diverged' | 'behind' | 'ahead' | 'even'; behind: number; ahead: number; upstream: string }

/** Which sentence the Detalhes panel shows about the branch against its remote. */
export function syncState(repo: Pick<GitRepo, 'upstream' | 'ahead' | 'behind' | 'fetching'>): SyncState {
  if (!repo.upstream) return { kind: 'no-upstream' }
  if (repo.fetching) return { kind: 'fetching' }
  const behind = repo.behind ?? 0
  const ahead = repo.ahead ?? 0
  const kind = behind > 0 && ahead > 0 ? 'diverged' : behind > 0 ? 'behind' : ahead > 0 ? 'ahead' : 'even'
  return { kind, behind, ahead, upstream: repo.upstream }
}
