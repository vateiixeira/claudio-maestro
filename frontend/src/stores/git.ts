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

  function reposFor(projectId: number): GitRepo[] {
    return byProject.value[projectId] ?? []
  }

  function isLoaded(projectId: number): boolean {
    return projectId in byProject.value
  }

  function set(projectId: number, repos: GitRepo[]): void {
    byProject.value[projectId] = repos
  }

  async function load(projectId: number): Promise<GitRepo[]> {
    const result = await api.getProjectGit(projectId)
    const repos = Array.isArray(result?.repos) ? result.repos : []
    set(projectId, repos)
    return repos
  }

  /** Loads once; failures just leave the project without branches. */
  function ensure(projectId: number): void {
    if (isLoaded(projectId)) return
    load(projectId).catch(() => {})
  }

  function applyEvent(event: WsEvent): void {
    const data = event.data as { project_id?: unknown; repos?: unknown } | null
    if (typeof data?.project_id !== 'number' || !Array.isArray(data.repos)) return
    set(data.project_id, data.repos as GitRepo[])
  }

  return { byProject, reposFor, isLoaded, set, load, ensure, applyEvent }
})
