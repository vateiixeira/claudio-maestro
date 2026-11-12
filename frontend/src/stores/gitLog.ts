import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { CommitDetail, FileDiff, LogCommit, LogDirection, LogQuery } from '../types/api'

export const LOG_PAGE = 30
const CACHE_ITEMS = 128
// Budget counts serialized UTF-16 bytes, in addition to the entry limit.
const CACHE_BYTES = 4 * 1024 * 1024

export interface LogState {
  ref: string | null
  branch: string | null
  upstream: string | null
  headSha: string | null
  upstreamSha: string | null
  commits: LogCommit[]
  incoming: LogCommit[]
  incomingCount: number | null
  outgoingCount: number | null
  nextSkip: number | null
  hasMore: boolean
  loading: boolean
  error: string | null
  updateAvailable: boolean
}

const emptyState = (ref: string | null): LogState => ({
  ref, branch: null, upstream: null, headSha: null, upstreamSha: null, commits: [], incoming: [],
  incomingCount: null, outgoingCount: null, nextSkip: null, hasMore: false, loading: false,
  error: null, updateAvailable: false,
})

function boundedCache<T>() {
  const entries = new Map<string, { promise: Promise<T>; bytes: number }>()
  let bytes = 0
  function remove(key: string): void {
    bytes -= entries.get(key)?.bytes ?? 0
    entries.delete(key)
  }
  function trim(): void {
    while (entries.size > CACHE_ITEMS || bytes > CACHE_BYTES) remove(entries.keys().next().value!)
  }
  return {
    get(key: string, load: () => Promise<T>): Promise<T> {
      const found = entries.get(key)
      if (found) {
        entries.delete(key)
        entries.set(key, found)
        return found.promise
      }
      const entry = { promise: load(), bytes: 0 }
      entries.set(key, entry)
      trim()
      void entry.promise.then((value) => {
        if (entries.get(key) !== entry) return
        entry.bytes = JSON.stringify(value).length * 2
        bytes += entry.bytes
        trim()
      }, () => { if (entries.get(key) === entry) remove(key) })
      return entry.promise
    },
    forget(prefix: string): void {
      for (const key of entries.keys()) if (key.startsWith(prefix)) remove(key)
    },
  }
}

/** Each direction has its own cursor, pinned to the repository's displayed snapshot. */
export const useGitLogStore = defineStore('gitLog', () => {
  const logs = ref<Record<string, LogState>>({})
  const details = boundedCache<CommitDetail>()
  const diffs = boundedCache<FileDiff>()
  const generations = new Map<string, number>()
  const keyOf = (projectId: number, repo: string, direction: LogDirection = 'all') => `${projectId}:${repo}:${direction}`

  function logFor(projectId: number, repo: string, direction: LogDirection = 'all'): LogState | null {
    return logs.value[keyOf(projectId, repo, direction)] ?? null
  }

  function invalidate(key: string): void {
    generations.set(key, (generations.get(key) ?? 0) + 1)
    delete logs.value[key]
  }

  function clearDirections(projectId: number, repo: string): void {
    for (const direction of ['incoming', 'outgoing'] as const) invalidate(keyOf(projectId, repo, direction))
  }

  function snapshot(state: LogState | null): LogQuery['snapshot'] {
    return state?.headSha ? { head: state.headSha, upstream: state.upstreamSha } : undefined
  }

  async function fetchPage(
    projectId: number, repo: string, refName: string | null, skip: number, limit?: number,
    append = false, direction: LogDirection = 'all', pinned?: LogQuery['snapshot'], probe = false,
  ): Promise<void> {
    const key = keyOf(projectId, repo, direction)
    const mine = (generations.get(key) ?? 0) + 1
    generations.set(key, mine)
    if (!logs.value[key]) logs.value[key] = emptyState(refName)
    const state = logs.value[key]
    state.loading = true
    try {
      const page = await api.getRepoLog(projectId, repo, refName, skip, limit, undefined, { direction, snapshot: pinned })
      if (generations.get(key) !== mine || logs.value[key] !== state) return
      if (probe && state.headSha) {
        // Keep the reader's rows, cursor, expanded commits and scroll position. A new
        // snapshot is applied only by the explicit reload action, never by a background event.
        state.updateAvailable = state.headSha !== page.head_sha || state.upstreamSha !== page.upstream_sha
          || state.branch !== page.branch || state.upstream !== page.upstream
        state.error = null
        return
      }
      const items = append ? [...state.commits, ...page.commits] : page.commits
      // The backend may resolve today's symbolic HEAD while reading the pinned SHAs.
      // Labels must belong to the displayed snapshot, including its secondary directions.
      const metadata = pinned ? logFor(projectId, repo) : null
      Object.assign(state, {
        ref: refName, branch: metadata ? metadata.branch : page.branch,
        upstream: metadata ? metadata.upstream : page.upstream,
        headSha: page.head_sha ?? null, upstreamSha: page.upstream_sha,
        commits: [...new Map(items.map((commit) => [commit.full_hash, commit])).values()],
        incoming: append ? state.incoming : page.incoming,
        incomingCount: page.incoming_count, outgoingCount: page.outgoing_count,
        nextSkip: page.has_more ? (page.next_skip ?? skip + page.commits.length) : null,
        hasMore: page.has_more, error: null, updateAvailable: append ? state.updateAvailable : false,
      })
    } catch (e) {
      if (generations.get(key) === mine) state.error = api.errorMessage(e)
    } finally {
      if (generations.get(key) === mine) state.loading = false
    }
  }

  /** Explicitly start a new snapshot; secondary directions must follow it. */
  function load(projectId: number, repo: string, refName?: string | null): Promise<void> {
    const current = logFor(projectId, repo)?.ref ?? null
    clearDirections(projectId, repo)
    return fetchPage(projectId, repo, refName === undefined ? current : refName, 0)
  }

  function loadMore(projectId: number, repo: string, direction: LogDirection = 'all'): Promise<void> {
    const state = logFor(projectId, repo, direction)
    if (!state || !state.hasMore || state.loading) return Promise.resolve()
    return fetchPage(projectId, repo, state.ref, state.nextSkip ?? state.commits.length, undefined, true, direction, snapshot(state))
  }

  function loadDirection(projectId: number, repo: string, direction: 'incoming' | 'outgoing'): Promise<void> {
    const current = logFor(projectId, repo)
    if (!current || current.loading || logFor(projectId, repo, direction)?.loading) return Promise.resolve()
    return fetchPage(projectId, repo, current.ref, 0, undefined, false, direction, snapshot(current))
  }

  /** Probe new refs without replacing the snapshot the user is reading. */
  function refresh(projectId: number, repo: string): Promise<void> {
    const state = logFor(projectId, repo)
    if (!state) return Promise.resolve()
    return fetchPage(projectId, repo, state.ref, 0, LOG_PAGE, false, 'all', undefined, true)
  }

  function setRef(projectId: number, repo: string, refName: string | null): Promise<void> {
    // A failed new reference must not allow pagination using the previous snapshot.
    invalidate(keyOf(projectId, repo))
    return load(projectId, repo, refName)
  }

  function commit(projectId: number, repo: string, sha: string): Promise<CommitDetail> {
    return details.get(`${projectId}:${repo}:${sha}`, () => api.getCommit(projectId, repo, sha))
  }

  function commitDiff(projectId: number, repo: string, sha: string, file: string): Promise<FileDiff> {
    return diffs.get(`${projectId}:${repo}:${sha}:${file}`, () => api.getCommitDiff(projectId, repo, sha, file))
  }

  function forgetProject(projectId: number): void {
    const prefix = `${projectId}:`
    for (const key of Object.keys(logs.value)) if (key.startsWith(prefix)) invalidate(key)
    for (const key of generations.keys()) if (key.startsWith(prefix)) generations.delete(key)
    details.forget(prefix)
    diffs.forget(prefix)
  }

  return { logs, logFor, load, loadMore, loadDirection, refresh, setRef, commit, commitDiff, forgetProject }
})
