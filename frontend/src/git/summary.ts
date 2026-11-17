import type { GitRepo } from '../types/api'

export interface GitTotals {
  ahead: number
  aheadRepos: number
  behind: number
  noUpstream: number
  changes: number
  errors: number
}

export type SummaryPartKind = 'ahead' | 'behind' | 'no-upstream' | 'changes' | 'errors' | 'clear'

export interface SummaryPart {
  part: SummaryPartKind
  text: string
}

/** Sums over the repositories; one with an error counts only in `errors`. */
export function gitTotals(repos: GitRepo[]): GitTotals {
  const totals: GitTotals = { ahead: 0, aheadRepos: 0, behind: 0, noUpstream: 0, changes: 0, errors: 0 }
  for (const repo of repos) {
    if (repo.error) {
      totals.errors += 1
      continue
    }
    const ahead = repo.ahead ?? 0
    if (ahead > 0) {
      totals.ahead += ahead
      totals.aheadRepos += 1
    }
    totals.behind += repo.behind ?? 0
    if (repo.upstream == null && !repo.detached) totals.noUpstream += 1
    totals.changes += repo.changed.staged + repo.changed.unstaged + repo.changed.untracked
  }
  return totals
}

/** The non-zero parts of the summary line, in order; "Tudo em dia" when there are none. */
export function summaryParts(totals: GitTotals): SummaryPart[] {
  const parts: SummaryPart[] = []
  if (totals.ahead > 0) {
    const commits = totals.ahead === 1 ? '1 commit' : `${totals.ahead} commits`
    const repos = totals.aheadRepos === 1 ? '1 repositório' : `${totals.aheadRepos} repositórios`
    parts.push({ part: 'ahead', text: `${commits} para enviar em ${repos}` })
  }
  if (totals.behind > 0) parts.push({ part: 'behind', text: `${totals.behind} para baixar` })
  if (totals.noUpstream > 0) parts.push({ part: 'no-upstream', text: `${totals.noUpstream} sem upstream` })
  if (totals.changes > 0) parts.push({ part: 'changes', text: totals.changes === 1 ? '1 alteração' : `${totals.changes} alterações` })
  if (totals.errors > 0) parts.push({ part: 'errors', text: `${totals.errors} com erro` })
  return parts.length ? parts : [{ part: 'clear', text: 'Tudo em dia' }]
}
