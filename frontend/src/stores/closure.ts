import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, errorMessage, getSessionClosure, resolveClosureItem } from '../api/http'
import type { SessionClosure } from '../types/api'

/** Closure checks of the sessions opened in Details. */
export const useClosureStore = defineStore('closure', () => {
  // Absent: never loaded. null: loaded, no check yet.
  const closures = ref<Record<string, SessionClosure | null>>({})
  const errors = ref<Record<string, string | null>>({})
  // The item being resolved per session, or null.
  const busy = ref<Record<string, string | null>>({})
  // Only the newest load per session wins. Events and invalidation also bump it,
  // so a load still in flight never overwrites fresher data.
  const tickets: Record<string, number> = {}
  // Bumped by invalidate() so open blocks reload even when they were already waiting for a load.
  const epoch = ref(0)

  function applyClosure(data: unknown): void {
    const d = data as { session_id?: unknown; closure?: unknown } | null
    if (!d || typeof d.session_id !== 'string') return
    if (!d.closure || typeof d.closure !== 'object') return
    tickets[d.session_id] = (tickets[d.session_id] ?? 0) + 1
    closures.value = { ...closures.value, [d.session_id]: d.closure as SessionClosure }
  }

  async function load(sessionId: string): Promise<void> {
    const mine = (tickets[sessionId] = (tickets[sessionId] ?? 0) + 1)
    try {
      const fresh = await getSessionClosure(sessionId)
      if (mine !== tickets[sessionId]) return
      closures.value = { ...closures.value, [sessionId]: fresh }
      errors.value = { ...errors.value, [sessionId]: null }
    } catch (e) {
      if (mine !== tickets[sessionId]) return
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    }
  }

  async function resolve(sessionId: string, item: string): Promise<void> {
    busy.value = { ...busy.value, [sessionId]: item }
    errors.value = { ...errors.value, [sessionId]: null }
    try {
      const fresh = await resolveClosureItem(sessionId, item)
      tickets[sessionId] = (tickets[sessionId] ?? 0) + 1
      closures.value = { ...closures.value, [sessionId]: fresh }
    } catch (e) {
      // The item vanished: read the check again first, because load() clears the error.
      if (e instanceof ApiError && e.status === 404) await load(sessionId)
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    } finally {
      busy.value = { ...busy.value, [sessionId]: null }
    }
  }

  /** Events were lost while the socket was down: loaded checks are read again. */
  function invalidate(): void {
    epoch.value += 1
    for (const id of Object.keys(tickets)) tickets[id] += 1
    closures.value = {}
  }

  return { closures, errors, busy, epoch, applyClosure, load, resolve, invalidate }
})
