import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { CommitDetail, FileDiff, LogCommit } from '../types/api'

export const LOG_PAGE = 30
const MAX_RELOAD = 300

export interface LogState {
  /** Ref asked for; null follows HEAD. */
  ref: string | null
  branch: string | null
  upstream: string | null
  upstreamSha: string | null
  commits: LogCommit[]
  incoming: LogCommit[]
  incomingCount: number | null
  outgoingCount: number | null
  hasMore: boolean
  loading: boolean
  error: string | null
}

const emptyState = (ref: string | null): LogState => ({
  ref, branch: null, upstream: null, upstreamSha: null, commits: [], incoming: [],
  incomingCount: null, outgoingCount: null, hasMore: false, loading: false, error: null,
})

/** History shown in the Commits section, per repository; commits and diffs cached by hash. */
export const useGitLogStore = defineStore('gitLog', () => {
  const logs = ref<Record<string, LogState>>({})
  // Commits never change, so their details and diffs are kept by hash.
  const details = new Map<string, Promise<CommitDetail>>()
  const diffs = new Map<string, Promise<FileDiff>>()
  const generations = new Map<string, number>()

  const keyOf = (projectId: number, repo: string) => `${projectId}:${repo}`

  function logFor(projectId: number, repo: string): LogState | null {
    return logs.value[keyOf(projectId, repo)] ?? null
  }

  async function fetchPage(projectId: number, repo: string, refName: string | null, skip: number, limit?: number, append = false): Promise<void> {
    const key = keyOf(projectId, repo)
    const mine = (generations.get(key) ?? 0) + 1
    generations.set(key, mine)
    if (!logs.value[key]) logs.value[key] = emptyState(refName)
    // Read back through the reactive map: the object assigned above is the raw one.
    const state = logs.value[key]
    state.loading = true
    try {
      const page = await api.getRepoLog(projectId, repo, refName, skip, limit)
      if (generations.get(key) !== mine) return
      Object.assign(state, {
        ref: refName,
        branch: page.branch,
        upstream: page.upstream,
        upstreamSha: page.upstream_sha,
        commits: append ? [...state.commits, ...page.commits] : page.commits,
        incoming: append ? state.incoming : page.incoming,
        incomingCount: page.incoming_count,
        outgoingCount: page.outgoing_count,
        hasMore: page.has_more,
        error: null,
      })
    } catch (e) {
      if (generations.get(key) !== mine) return
      state.error = api.errorMessage(e)
    } finally {
      if (generations.get(key) === mine) state.loading = false
    }
  }

  /** First page of `refName` (default: what is shown now, or HEAD). */
  function load(projectId: number, repo: string, refName?: string | null): Promise<void> {
    const current = logFor(projectId, repo)?.ref ?? null
    return fetchPage(projectId, repo, refName === undefined ? current : refName, 0)
  }

  function loadMore(projectId: number, repo: string): Promise<void> {
    const state = logFor(projectId, repo)
    if (!state || !state.hasMore || state.loading) return Promise.resolve()
    return fetchPage(projectId, repo, state.ref, state.commits.length, undefined, true)
  }

  /** Git changed: reread what is shown, keeping the pages already loaded. */
  function refresh(projectId: number, repo: string): Promise<void> {
    const state = logFor(projectId, repo)
    if (!state) return Promise.resolve()
    const limit = Math.min(MAX_RELOAD, Math.max(LOG_PAGE, state.commits.length))
    return fetchPage(projectId, repo, state.ref, 0, limit)
  }

  function setRef(projectId: number, repo: string, refName: string | null): Promise<void> {
    return fetchPage(projectId, repo, refName, 0)
  }

  function commit(projectId: number, repo: string, sha: string): Promise<CommitDetail> {
    const key = `${projectId}:${repo}:${sha}`
    let found = details.get(key)
    if (!found) {
      found = api.getCommit(projectId, repo, sha)
      found.catch(() => details.delete(key))
      details.set(key, found)
    }
    return found
  }

  function commitDiff(projectId: number, repo: string, sha: string, file: string): Promise<FileDiff> {
    const key = `${projectId}:${repo}:${sha}:${file}`
    let found = diffs.get(key)
    if (!found) {
      found = api.getCommitDiff(projectId, repo, sha, file)
      found.catch(() => diffs.delete(key))
      diffs.set(key, found)
    }
    return found
  }

  return { logs, logFor, load, loadMore, refresh, setRef, commit, commitDiff }
})
