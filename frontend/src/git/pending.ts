import type { GitRepo, RepoDetails } from '../types/api'

/** A repository that asks for attention: error, changes, a merge, or commits to send or pull. */
export function isPending(repo: GitRepo | RepoDetails): boolean {
  const files = 'files' in repo ? repo.files.length : 0
  const merging = 'state' in repo ? Boolean(repo.state?.merging) : false
  return Boolean(
    repo.error
    || repo.changed.staged + repo.changed.unstaged + repo.changed.untracked > 0
    || files > 0
    || merging
    || (repo.ahead ?? 0) > 0
    || (repo.behind ?? 0) > 0,
  )
}

export function pendingCount(repos: (GitRepo | RepoDetails)[]): number {
  return repos.filter(isPending).length
}
