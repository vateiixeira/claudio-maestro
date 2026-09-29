import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { GitRepo } from '../types/api'
import type { WsEvent } from '../types/events'

/** Branch as the user reads it: name, "HEAD solto · hash" or "branch indisponível". */
export function branchText(repo: Pick<GitRepo, 'branch' | 'detached' | 'head' | 'error'>): string {
  if (repo.error) return 'branch indisponível'
  if (repo.detached) return `HEAD solto · ${repo.head ?? ''}`.trim()
  return repo.branch ?? 'branch indisponível'
}

/** Branch of a folder listing: the name, or "HEAD solto · hash" when detached (`branch` is then the hash). */
export function dirBranchText(branch: string, detached: boolean): string {
  return detached ? `HEAD solto · ${branch}` : branch
}

/** "api · feat/x", or just the branch for the project folder itself. */
export function repoLabel(repo: GitRepo): string {
  return repo.rel_path === '.' ? branchText(repo) : `${repo.rel_path} · ${branchText(repo)}`
}

export function changedCount(repo: GitRepo): number {
  return repo.changed.staged + repo.changed.unstaged + repo.changed.untracked
}

/** Repositories found in each project folder, with their branch. */
export const useGitStore = defineStore('git', () => {
  const byProject = ref<Record<number, GitRepo[]>>({})
  // Projects with more repositories than the limit (only the first ones are tracked).
  const limited = ref<Record<number, boolean>>({})

  function reposFor(projectId: number): GitRepo[] {
    return byProject.value[projectId] ?? []
  }

  function isLoaded(projectId: number): boolean {
    return projectId in byProject.value
  }

  function limitReached(projectId: number): boolean {
    return limited.value[projectId] === true
  }

  /** `limit` is left as it was when not given. */
  function set(projectId: number, repos: GitRepo[], limit?: boolean): void {
    byProject.value[projectId] = repos
    if (typeof limit === 'boolean') limited.value[projectId] = limit
  }

  async function load(projectId: number): Promise<GitRepo[]> {
    const result = await api.getProjectGit(projectId)
    const repos = Array.isArray(result?.repos) ? result.repos : []
    set(projectId, repos, result?.limit_reached === true)
    return repos
  }

  /** Loads once; failures just leave the project without branches. */
  function ensure(projectId: number): void {
    if (isLoaded(projectId)) return
    load(projectId).catch(() => {})
  }

  function applyEvent(event: WsEvent): void {
    const data = event.data as { project_id?: unknown; repos?: unknown; limit_reached?: unknown } | null
    if (typeof data?.project_id !== 'number' || !Array.isArray(data.repos)) return
    set(data.project_id, data.repos as GitRepo[], typeof data.limit_reached === 'boolean' ? data.limit_reached : undefined)
  }

  return { byProject, reposFor, isLoaded, limitReached, set, load, ensure, applyEvent }
})
