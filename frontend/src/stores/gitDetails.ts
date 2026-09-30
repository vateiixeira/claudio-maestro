import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
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

  function revisionFor(projectId: number): number {
    return revisions.value[projectId] ?? 0
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
  async function load(projectId: number): Promise<void> {
    const mine = (generations.get(projectId) ?? 0) + 1
    generations.set(projectId, mine)
    abortPending(projectId)
    const controller = new AbortController()
    controllers.set(projectId, controller)
    loading.value[projectId] = true
    try {
      const result = await api.getProjectGitDetails(projectId, controller.signal)
      if (generations.get(projectId) !== mine) return
      byProject.value[projectId] = {
        repos: Array.isArray(result?.repos) ? result.repos : [],
        limit_reached: result?.limit_reached === true,
      }
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

  function clearTimer(projectId: number): void {
    const timer = timers.get(projectId)
    if (timer !== undefined) clearTimeout(timer)
    timers.delete(projectId)
  }

  /** A screen starts showing the project's details: loads them and keeps them fresh. */
  function open(projectId: number): void {
    openCount.set(projectId, (openCount.get(projectId) ?? 0) + 1)
    void load(projectId)
  }

  function close(projectId: number): void {
    const count = (openCount.get(projectId) ?? 0) - 1
    if (count > 0) {
      openCount.set(projectId, count)
      return
    }
    openCount.delete(projectId)
    clearTimer(projectId)
    // An answer still on its way has nobody to show it to.
    generations.set(projectId, (generations.get(projectId) ?? 0) + 1)
    abortPending(projectId)
    loading.value[projectId] = false
  }

  /** `project.git` arrived: reread soon, if someone is looking. */
  function notifyChanged(projectId: number): void {
    if (!openCount.has(projectId)) return
    clearTimer(projectId)
    timers.set(projectId, setTimeout(() => {
      timers.delete(projectId)
      void load(projectId)
    }, RELOAD_DEBOUNCE_MS))
  }

  /** After the socket came back, events were lost. */
  function reloadOpen(): void {
    openCount.forEach((_count, projectId) => void load(projectId))
  }

  return { byProject, reposFor, isLoaded, errorFor, revisionFor, isLoading, load, open, close, notifyChanged, reloadOpen }
})
