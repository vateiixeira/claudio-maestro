import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, getSessionDigest, requestSessionDigest } from '../api/http'
import type { DigestStatus, SessionDigest } from '../types/api'

function isStatus(value: unknown): value is DigestStatus {
  const v = value as Partial<DigestStatus> | null
  return !!v && typeof v === 'object' && typeof v.enabled === 'boolean' && typeof v.running === 'boolean'
}

/** Digest agent state and the summaries of the sessions opened in Details. */
export const useDigestStore = defineStore('digest', () => {
  const status = ref<DigestStatus | null>(null)
  // Absent: never loaded. null: loaded, no summary yet.
  const digests = ref<Record<string, SessionDigest | null>>({})
  const pending = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, string | null>>({})
  // Only the newest load per session wins. Events and invalidation also bump it,
  // so a load still in flight never overwrites fresher data.
  const tickets: Record<string, number> = {}
  // Bumped by invalidate() so open sections reload even when they were already waiting for a load.
  const epoch = ref(0)

  function applyStatus(data: unknown): void {
    if (isStatus(data)) status.value = { ...data }
  }

  function applyDigest(data: unknown): void {
    const d = data as { session_id?: unknown; digest?: unknown } | null
    if (!d || typeof d.session_id !== 'string') return
    pending.value = { ...pending.value, [d.session_id]: false }
    if (!d.digest || typeof d.digest !== 'object') return
    tickets[d.session_id] = (tickets[d.session_id] ?? 0) + 1
    digests.value = { ...digests.value, [d.session_id]: d.digest as SessionDigest }
  }

  async function load(sessionId: string): Promise<void> {
    const mine = (tickets[sessionId] = (tickets[sessionId] ?? 0) + 1)
    try {
      const fresh = await getSessionDigest(sessionId)
      if (mine !== tickets[sessionId]) return
      digests.value = { ...digests.value, [sessionId]: fresh }
      errors.value = { ...errors.value, [sessionId]: null }
    } catch (e) {
      if (mine !== tickets[sessionId]) return
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    }
  }

  async function request(sessionId: string): Promise<void> {
    pending.value = { ...pending.value, [sessionId]: true }
    errors.value = { ...errors.value, [sessionId]: null }
    try {
      await requestSessionDigest(sessionId)
    } catch (e) {
      pending.value = { ...pending.value, [sessionId]: false }
      errors.value = { ...errors.value, [sessionId]: errorMessage(e) }
    }
  }

  /** Events were lost while the socket was down: loaded summaries are read again. */
  function invalidate(): void {
    epoch.value += 1
    for (const id of Object.keys(tickets)) tickets[id] += 1
    digests.value = {}
    pending.value = {}
  }

  return { status, digests, pending, errors, epoch, applyStatus, applyDigest, load, request, invalidate }
})
