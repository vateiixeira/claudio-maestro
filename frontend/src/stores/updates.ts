import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { UpdateJob, UpdateState } from '../types/api'

const DISMISSED_KEY = 'maestro:update-dismissed'

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

const RESULT_SEEN_KEY = 'maestro:update-result-seen'
const AGENTD_DISMISSED_KEY = 'maestro:agentd-notice-dismissed'
export const RESTART_TIMEOUT_MS = 60_000
/** Swapped in tests. */
export const pageReload = { reload: (): void => window.location.reload() }

function readKey(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function writeKey(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* blocked storage: only this tab remembers */ }
}

function isJob(data: unknown): data is UpdateJob {
  if (typeof data !== 'object' || data === null) return false
  const value = data as Partial<UpdateJob>
  return typeof value.state === 'string' && Array.isArray(value.lines)
}

/** The number of open sessions in the backend's structured 409 ("sessions_drop"), or null for any other error. */
function droppedSessions(data: Record<string, unknown> | null): number | null {
  if (!data || data.code !== 'sessions_drop') return null
  const n = data.sessions
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}

function isUpdateState(data: unknown): data is UpdateState {
  if (typeof data !== 'object' || data === null) return false
  const value = data as Partial<UpdateState>
  return typeof value.current === 'string' && typeof value.available === 'boolean' && typeof value.enabled === 'boolean'
}

/** Installed version and whether a newer release exists (the backend checks GitHub once a day). */
export const useUpdatesStore = defineStore('updates', () => {
  const state = ref<UpdateState | null>(null)
  const dismissed = ref<string | null>(readDismissed())
  const modalOpen = ref(false)
  const applying = ref(false)
  const applyError = ref<string | null>(null)
  // Set when the backend refuses because sessions are open (the page's own count may be old): how many.
  const confirmSessions = ref<number | null>(null)
  const restartTimedOut = ref(false)
  const resultSeen = ref<string | null>(readKey(RESULT_SEEN_KEY))
  const agentdDismissed = ref<string | null>(readKey(AGENTD_DISMISSED_KEY))
  const agentdRestarting = ref(false)
  const agentdError = ref<string | null>(null)
  // The version this page was built for: a different `current` means the app restarted on a new one.
  let pageVersion: string | null = null
  let restartTimer: ReturnType<typeof setTimeout> | undefined
  // Bumped by every `app.update` event, so a slower GET started before it does not overwrite it.
  let applied = 0
  // Bumped by every progress event: a slower GET or POST must not bring back an older job.
  let progressSeen = 0

  const showNotice = computed(() => {
    const s = state.value
    return !!s && s.enabled && s.available && !!s.latest && s.latest.version !== dismissed.value
  })

  function watchRestart(): void {
    if (state.value?.job?.state === 'restarting') {
      if (restartTimer === undefined) restartTimer = setTimeout(() => (restartTimedOut.value = true), RESTART_TIMEOUT_MS)
      return
    }
    clearTimeout(restartTimer)
    restartTimer = undefined
    restartTimedOut.value = false
  }

  function receive(next: UpdateState): void {
    if (pageVersion === null) pageVersion = next.current
    else if (next.current !== pageVersion) {
      pageReload.reload()
      return
    }
    state.value = { ...(state.value ?? {}), ...next }
    watchRestart()
  }

  async function load(): Promise<void> {
    const before = applied
    const progressBefore = progressSeen
    const result = await api.getUpdates()
    if (applied !== before) return
    if (progressSeen === progressBefore) {
      receive(result)
      return
    }
    // A progress event arrived meanwhile: the job in this response is older than the one we have.
    const { job: _older, ...rest } = result
    receive(rest as UpdateState)
  }

  function apply(data: unknown): void {
    if (!isUpdateState(data)) return
    applied += 1
    receive(data)
  }

  function applyProgress(data: unknown): void {
    if (!isJob(data) || !state.value) return
    progressSeen += 1
    state.value = { ...state.value, job: data }
    watchRestart()
  }

  async function startUpdate(confirmSessionsDrop = false): Promise<void> {
    const version = state.value?.latest?.version
    if (!version || applying.value) return
    applying.value = true
    applyError.value = null
    confirmSessions.value = null
    const progressBefore = progressSeen
    try {
      const result = await api.applyUpdate(version, confirmSessionsDrop)
      // Progress events may already have arrived (and are newer than this response): keep them.
      if (result.job && state.value && progressSeen === progressBefore) {
        state.value = { ...state.value, job: result.job }
      }
      watchRestart()
    } catch (e) {
      const sessions = e instanceof api.ApiError && e.status === 409 ? droppedSessions(e.data) : null
      if (sessions !== null) confirmSessions.value = sessions
      else applyError.value = e instanceof Error ? e.message : 'Não foi possível iniciar a atualização.'
    } finally {
      applying.value = false
    }
  }

  const showUpdatedNotice = computed(() => {
    const result = state.value?.last_result
    return !!result && result.to !== resultSeen.value
  })

  function dismissUpdatedNotice(): void {
    const to = state.value?.last_result?.to
    if (!to) return
    resultSeen.value = to
    writeKey(RESULT_SEEN_KEY, to)
  }

  const showAgentdNotice = computed(() => {
    const result = state.value?.last_result
    return !!result?.agentd_changed && !!state.value?.agentd?.enabled && result.to !== agentdDismissed.value
  })
  /** Sessions that would drop on an agentd restart: the larger of the agentd's live children and the app's live sessions. */
  const agentdOpenSessions = computed(() => Math.max(state.value?.agentd?.live_children ?? 0, state.value?.live_sessions ?? 0))
  const agentdBusy = computed(() => agentdOpenSessions.value > 0)

  function dismissAgentdNotice(): void {
    const to = state.value?.last_result?.to
    if (!to) return
    agentdDismissed.value = to
    writeKey(AGENTD_DISMISSED_KEY, to)
  }

  async function restartAgentd(): Promise<void> {
    if (agentdRestarting.value) return
    agentdRestarting.value = true
    agentdError.value = null
    try {
      await api.restartAgentd()
      dismissAgentdNotice()
    } catch (e) {
      agentdError.value = e instanceof Error ? e.message : 'Não foi possível reiniciar o agentd.'
    } finally {
      agentdRestarting.value = false
    }
  }

  function dismiss(): void {
    const version = state.value?.latest?.version
    if (!version) return
    dismissed.value = version
    try {
      localStorage.setItem(DISMISSED_KEY, version)
    } catch {
      // Blocked storage: the notice stays hidden only in this tab.
    }
    modalOpen.value = false
    confirmSessions.value = null
  }

  function openModal(): void {
    if (state.value?.latest) modalOpen.value = true
  }

  function closeModal(): void {
    modalOpen.value = false
    confirmSessions.value = null
  }

  return {
    state, showNotice, modalOpen, load, apply, dismiss, openModal, closeModal,
    applyProgress, startUpdate, applying, applyError, confirmSessions, restartTimedOut,
    showUpdatedNotice, dismissUpdatedNotice,
    showAgentdNotice, agentdBusy, agentdOpenSessions, agentdRestarting, agentdError, restartAgentd, dismissAgentdNotice,
  }
})
