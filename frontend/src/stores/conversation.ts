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
export const useConversationStore = defineStore('conversation', () => {
  const bySession = ref<Record<string, Conversation>>({})
  const buffers = new Map<string, WsEvent[]>()

  function get(sessionId: string): Conversation | undefined {
    return bySession.value[sessionId]
  }

  async function load(sessionId: string): Promise<Conversation> {
    const buffer: WsEvent[] = []
    buffers.set(sessionId, buffer)
    try {
      const snapshot = await api.getSession(sessionId)
      const conv = conversationFromSnapshot(snapshot)
      const previous = bySession.value[sessionId]
      if (previous) conv.lastResult = previous.lastResult
      for (const event of buffer) applyConversationEvent(conv, event)
      bySession.value[sessionId] = conv
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
    if (conv) applyConversationEvent(conv, event)
  }

  function resolvePrompt(sessionId: string, promptId: string): void {
    const conv = bySession.value[sessionId]
    if (conv) removePrompt(conv, promptId)
  }

  function forget(sessionId: string): void {
    delete bySession.value[sessionId]
    buffers.delete(sessionId)
  }

  return { bySession, get, load, receive, resolvePrompt, forget }
})
