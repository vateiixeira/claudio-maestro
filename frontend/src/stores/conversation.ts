import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'
import type { SessionState } from '../types/api'
import type {
  ConversationItem,
  PermissionPrompt,
  SessionInit,
  SessionSnapshot,
  TurnResult,
} from '../types/conversation'
import type { WsEvent } from '../types/events'

export interface Conversation {
  sessionId: string
  projectId: number | null
  title: string
  cwd: string
  state: SessionState
  error: string | null
  seq: number
  items: ConversationItem[]
  prompts: PermissionPrompt[]
  init: SessionInit | null
  lastResult: TurnResult | null
  historyTruncated: boolean
  externalActivity: boolean
}

export function emptyConversation(sessionId: string): Conversation {
  return {
    sessionId,
    projectId: null,
    title: '',
    cwd: '',
    state: 'closed',
    error: null,
    seq: 0,
    items: [],
    prompts: [],
    init: null,
    lastResult: null,
    historyTruncated: false,
    externalActivity: false,
  }
}

export function conversationFromSnapshot(snapshot: SessionSnapshot): Conversation {
  return {
    sessionId: snapshot.session_id,
    projectId: snapshot.project_id,
    title: snapshot.title,
    cwd: snapshot.cwd,
    state: snapshot.state,
    error: snapshot.error ?? null,
    seq: snapshot.seq,
    items: [...snapshot.items],
    prompts: [...snapshot.prompts],
    init: snapshot.init ?? null,
    lastResult: null,
    historyTruncated: snapshot.history_truncated === true,
    externalActivity: snapshot.external_activity === true,
  }
}

/**
 * Applies one event to a conversation, in place. Events whose `seq` is not newer
 * than the conversation's are ignored. Returns whether the event was applied.
 * Has no Vue dependency so it can be tested alone.
 */
export function applyConversationEvent(conv: Conversation, event: WsEvent): boolean {
  if (event.seq <= conv.seq) return false
  conv.seq = event.seq
  const data = (event.data ?? {}) as Record<string, unknown>

  switch (event.type) {
    case 'item.upsert': {
      const item = data as unknown as ConversationItem
      const index = conv.items.findIndex((i) => i.id === item.id)
      if (index >= 0) conv.items[index] = item
      else conv.items.push(item)
      break
    }
    case 'item.append': {
      const item = conv.items.find((i) => i.id === data.item_id)
      if (item && 'text' in item) item.text += String(data.text ?? '')
      break
    }
    case 'session.state':
      conv.state = data.state as SessionState
      conv.error = (data.error as string | null) ?? null
      break
    case 'session.title':
      conv.title = String(data.title ?? '')
      break
    case 'session.updated':
      if (typeof data.title === 'string' && data.title) conv.title = data.title
      break
    case 'session.init':
      conv.init = data as unknown as SessionInit
      break
    case 'turn.result':
      conv.lastResult = data as unknown as TurnResult
      break
    case 'prompt.request': {
      const prompt = data as unknown as PermissionPrompt
      if (!conv.prompts.some((p) => p.prompt_id === prompt.prompt_id)) conv.prompts.push(prompt)
      break
    }
    case 'prompt.resolved':
      removePrompt(conv, String(data.prompt_id))
      break
  }
  return true
}

export function removePrompt(conv: Conversation, promptId: string): void {
  conv.prompts = conv.prompts.filter((p) => p.prompt_id !== promptId)
}

/**
 * Open conversations by session id. `load` fetches the snapshot; events that arrive
 * while it loads are held and applied afterwards, dropping those the snapshot already has.
 */
/** How long the external activity warning stays up. */
export const EXTERNAL_ACTIVITY_MS = 60_000

export const useConversationStore = defineStore('conversation', () => {
  const bySession = ref<Record<string, Conversation>>({})
  const buffers = new Map<string, WsEvent[]>()
  const externalTimers = new Map<string, ReturnType<typeof setTimeout>>()

  function get(sessionId: string): Conversation | undefined {
    return bySession.value[sessionId]
  }

  // One snapshot load per session; a request during it asks for one more at the end.
  const loading = new Map<string, Promise<Conversation>>()
  const reloadRequested = new Set<string>()

  function load(sessionId: string): Promise<Conversation> {
    const current = loading.get(sessionId)
    if (current) {
      reloadRequested.add(sessionId)
      return current
    }
    const promise = loadUntilCurrent(sessionId).finally(() => {
      loading.delete(sessionId)
      reloadRequested.delete(sessionId)
    })
    loading.set(sessionId, promise)
    return promise
  }

  async function loadUntilCurrent(sessionId: string): Promise<Conversation> {
    for (;;) {
      reloadRequested.delete(sessionId)
      const conv = await loadOnce(sessionId)
      if (conv && !reloadRequested.has(sessionId)) return conv
    }
  }

  /** Fetches and applies one snapshot; null when a newer one is needed. */
  async function loadOnce(sessionId: string): Promise<Conversation | null> {
    const buffer: WsEvent[] = []
    buffers.set(sessionId, buffer)
    try {
      const snapshot = await api.getSession(sessionId)
      // Another load was asked for, or the backend reloaded the conversation after
      // this snapshot: fetch it again.
      if (
        reloadRequested.has(sessionId) ||
        buffer.some((e) => e.type === 'conversation.reset' && e.seq > snapshot.seq)
      ) {
        reloadRequested.add(sessionId)
        return null
      }
      const conv = conversationFromSnapshot(snapshot)
      const previous = bySession.value[sessionId]
      if (previous) conv.lastResult = previous.lastResult
      for (const event of buffer) applyConversationEvent(conv, event)
      bySession.value[sessionId] = conv
      // The newest snapshot decides: false clears the warning, true restarts its minute.
      if (conv.externalActivity) noteExternalActivity(sessionId)
      else clearExternalTimer(sessionId)
      return bySession.value[sessionId]!
    } finally {
      if (buffers.get(sessionId) === buffer) buffers.delete(sessionId)
    }
  }

  function receive(event: WsEvent): void {
    const buffer = buffers.get(event.session_id)
    if (buffer) {
      buffer.push(event)
      return
    }
    const conv = bySession.value[event.session_id]
    if (!conv) return
    if (event.type === 'conversation.reset') {
      // The backend replaced the conversation (file changed outside the app).
      if (event.seq > conv.seq) load(event.session_id).catch(() => {})
      return
    }
    applyConversationEvent(conv, event)
  }

  function resolvePrompt(sessionId: string, promptId: string): void {
    const conv = bySession.value[sessionId]
    if (conv) removePrompt(conv, promptId)
  }

  function clearExternalTimer(sessionId: string): void {
    const timer = externalTimers.get(sessionId)
    if (timer) clearTimeout(timer)
    externalTimers.delete(sessionId)
  }

  /** The backend saw another process write to the session in the last minute; shown for 60 s. */
  function noteExternalActivity(sessionId: string): void {
    const conv = bySession.value[sessionId]
    if (!conv) return
    conv.externalActivity = true
    clearExternalTimer(sessionId)
    externalTimers.set(sessionId, setTimeout(() => {
      externalTimers.delete(sessionId)
      const current = bySession.value[sessionId]
      if (current) current.externalActivity = false
    }, EXTERNAL_ACTIVITY_MS))
  }

  function forget(sessionId: string): void {
    clearExternalTimer(sessionId)
    delete bySession.value[sessionId]
    buffers.delete(sessionId)
  }

  return { bySession, get, load, receive, resolvePrompt, noteExternalActivity, forget }
})
