import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import { useGitStore } from './git'
import type { ProjectGitDetails, RepoDetails } from '../types/api'

/** Wait for events to settle before rereading: a `git commit` fires several in a row. */
export const RELOAD_DEBOUNCE_MS = 500

/**
 * Files and latest commits of the repositories of the projects being looked at.
 * Only projects with an open screen (`open`/`close`) are reloaded when git changes.
 */
export const useGitDetailsStore = defineStore('gitDetails', () => {
  const byProject = ref<Record<number, ProjectGitDetails>>({})
  const errors = ref<Record<number, string | null>>({})
  const loading = ref<Record<number, boolean>>({})
  // Bumped on every successful load, so views can reread what hangs off the details (diffs).
  const revisions = ref<Record<number, number>>({})
  const repoRevisions = ref<Record<string, number>>({})
  const historyRevisions = ref<Record<string, number>>({})
  const keyOf = (projectId: number, repo: string) => `${projectId}:${repo}`
  type Mutation = { projectId: number; repo: string; externalChanged: boolean }
  const mutations = new Map<string, Mutation>()
  const completedMutations = new Map<string, Mutation>()
  const pendingPaths = new Map<number, Set<string> | null>()

  function historyKey(repo: RepoDetails): string {
    return JSON.stringify([repo.head_sha, repo.branch, repo.detached, repo.upstream,
      repo.ahead, repo.behind, repo.fetched_at, repo.error, repo.refs_signature])
  }

  function revise(projectId: number, before: RepoDetails | undefined, repo: RepoDetails, files: boolean, history: boolean): void {
    const key = keyOf(projectId, repo.path)
    if (files || !before || JSON.stringify(before.files) !== JSON.stringify(repo.files)) {
      repoRevisions.value[key] = (repoRevisions.value[key] ?? 0) + 1
    }
    if (history || !before || repo.refs_signature === null || historyKey(before) !== historyKey(repo)) {
      historyRevisions.value[key] = (historyRevisions.value[key] ?? 0) + 1
    }
  }

  // Plain maps: nothing renders from them.
  const openCount = new Map<number, number>()
  const generations = new Map<number, number>()
  const timers = new Map<number, ReturnType<typeof setTimeout>>()
  const controllers = new Map<number, AbortController>()

  function reposFor(projectId: number): RepoDetails[] {
    return byProject.value[projectId]?.repos ?? []
  }

  function isLoaded(projectId: number): boolean {
    return projectId in byProject.value
  }

  function errorFor(projectId: number): string | null {
    return errors.value[projectId] ?? null
  }

  function revisionFor(projectId: number, repo?: string): number {
    return repo === undefined ? (revisions.value[projectId] ?? 0) : (repoRevisions.value[keyOf(projectId, repo)] ?? 0)
  }

  function historyRevisionFor(projectId: number, repo: string): number {
    return historyRevisions.value[keyOf(projectId, repo)] ?? 0
  }

  function isLoading(projectId: number): boolean {
    return loading.value[projectId] === true
  }

  function abortPending(projectId: number): void {
    controllers.get(projectId)?.abort()
    controllers.delete(projectId)
  }

  /**
   * Answers that arrive after a newer request started are dropped, and the older
   * request is aborted (its failure is never shown: the generation no longer matches).
   */
  async function load(projectId: number, forceHistory = true, paths: Set<string> | null = null): Promise<void> {
    const mine = (generations.get(projectId) ?? 0) + 1
    generations.set(projectId, mine)
    abortPending(projectId)
    const controller = new AbortController()
    controllers.set(projectId, controller)
    loading.value[projectId] = true
    const git = useGitStore()
    const summaryVersion = git.versionFor(projectId)
    try {
      const result = await api.getProjectGitDetails(projectId, controller.signal)
      if (generations.get(projectId) !== mine) return
      const repos = Array.isArray(result?.repos) ? result.repos : []
      const previous = new Map(reposFor(projectId).map(repo => [repo.path, repo]))
      for (const repo of repos) revise(projectId, previous.get(repo.path), repo, paths === null || paths.has(repo.path), forceHistory)
      byProject.value[projectId] = {
        repos,
        limit_reached: result?.limit_reached === true,
      }
      // Details already contain the summary; do not scan the project again for the sidebar.
      // A newer event or fetch remains authoritative if it arrived during this read.
      git.set(projectId, repos, result?.limit_reached === true, summaryVersion)
      errors.value[projectId] = null
      revisions.value[projectId] = revisionFor(projectId) + 1
    } catch (e) {
      if (generations.get(projectId) !== mine) return
      errors.value[projectId] = api.errorMessage(e)
    } finally {
      if (generations.get(projectId) === mine) {
        loading.value[projectId] = false
        controllers.delete(projectId)
      }
    }
  }

  /** An action answered with the repository as it is now: show it without rereading all. */
  function replaceRepo(projectId: number, repo: RepoDetails): void {
    const current = byProject.value[projectId]
    if (!current) return
    const index = current.repos.findIndex((r) => r.path === repo.path)
    if (index < 0) return
    // A reread that started before the action would bring back the state from before it.
    const rereading = controllers.has(projectId)
    generations.set(projectId, (generations.get(projectId) ?? 0) + 1)
    abortPending(projectId)
    loading.value[projectId] = false
    revise(projectId, current.repos[index], repo, true, false)
    current.repos.splice(index, 1, repo)
    revisions.value[projectId] = revisionFor(projectId) + 1
    // The reread that was dropped also carried the other repositories of the project: ask again.
    if (rereading) notifyChanged(projectId)
  }

  function clearTimer(projectId: number): void {
    const timer = timers.get(projectId)
    if (timer !== undefined) clearTimeout(timer)
    timers.delete(projectId)
  }

  /** A screen starts showing the project's details: loads them and keeps them fresh. */
  function open(projectId: number): void {
    const count = openCount.get(projectId) ?? 0
    openCount.set(projectId, count + 1)
    if (count === 0 && !controllers.has(projectId)) void load(projectId)
  }

  function close(projectId: number): void {
    const count = (openCount.get(projectId) ?? 0) - 1
    if (count > 0) {
      openCount.set(projectId, count)
      return
    }
    openCount.delete(projectId)
    clearTimer(projectId)
    pendingPaths.delete(projectId)
    // An answer still on its way has nobody to show it to.
    generations.set(projectId, (generations.get(projectId) ?? 0) + 1)
    abortPending(projectId)
    loading.value[projectId] = false
  }

  /** Known local mutations already return their repo; external changes keep their own invalidation. */
  function notifyChanged(projectId: number, paths: string[] | null = null, mutationId?: string, mutationRepo?: string): void {
    const known = mutationId ? mutations.get(mutationId) ?? completedMutations.get(mutationId) : undefined
    const acknowledged = known?.projectId === projectId && known.repo === mutationRepo
    const changed = paths === null ? null : paths.filter(path => !acknowledged || path !== mutationRepo)
    if (changed !== null && changed.length === 0) return
    for (const mutation of mutations.values()) {
      if (mutation.projectId === projectId && (changed === null || changed.includes(mutation.repo))) mutation.externalChanged = true
    }
    if (!openCount.has(projectId)) return
    const pending = pendingPaths.get(projectId)
    pendingPaths.set(projectId, changed === null || pending === null ? null : new Set([...(pending ?? []), ...changed]))
    clearTimer(projectId)
    timers.set(projectId, setTimeout(() => {
      timers.delete(projectId)
      const selected = pendingPaths.get(projectId) ?? null
      pendingPaths.delete(projectId)
      void load(projectId, false, selected)
    }, RELOAD_DEBOUNCE_MS))
  }

  function beginMutation(projectId: number, repo: string, id: string): void {
    mutations.set(id, { projectId, repo, externalChanged: false })
  }

  function finishMutation(projectId: number, repo: string, id: string, result?: RepoDetails): void {
    const pending = mutations.get(id)
    mutations.delete(id)
    if (result) {
      completedMutations.set(id, { projectId, repo, externalChanged: false })
      while (completedMutations.size > 128) completedMutations.delete(completedMutations.keys().next().value!)
      replaceRepo(projectId, result)
    }
    // A newer external snapshot may have arrived before this HTTP result. Reconcile again;
    // never cancel an external timer just because our mutation answered successfully.
    if (!result || pending?.externalChanged) notifyChanged(projectId, [repo])
  }

  /** After the socket came back, events were lost; force both domains to be reconciled. */
  function reloadOpen(): void {
    completedMutations.clear()
    for (const mutation of mutations.values()) mutation.externalChanged = true
    openCount.forEach((_count, projectId) => void load(projectId))
  }

  return { byProject, reposFor, isLoaded, errorFor, revisionFor, historyRevisionFor, beginMutation, finishMutation, isLoading, load, replaceRepo, open, close, notifyChanged, reloadOpen }
})
