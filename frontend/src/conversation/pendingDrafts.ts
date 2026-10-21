import type { DraftImage } from './images'

export interface PendingDraft {
  text: string
  error: string | null
  /** Images that were attached to the first prompt. */
  images?: DraftImage[]
}

// A first prompt that could not be sent, delivered now or when the composer opens next.
const drafts = new Map<string, PendingDraft>()
const listeners = new Map<string, (draft: PendingDraft) => void>()

export function setPendingDraft(sessionId: string, draft: PendingDraft): void {
  const listener = listeners.get(sessionId)
  if (listener) listener(draft)
  else drafts.set(sessionId, draft)
}

/** Delivers late failures directly to the composer mounted for this session. */
export function onPendingDraft(sessionId: string, listener: (draft: PendingDraft) => void): () => void {
  listeners.set(sessionId, listener)
  return () => {
    if (listeners.get(sessionId) === listener) listeners.delete(sessionId)
  }
}

/** The draft for this session, removed on read (it fills one composer once). */
export function takePendingDraft(sessionId: string): PendingDraft | null {
  const draft = drafts.get(sessionId) ?? null
  drafts.delete(sessionId)
  return draft
}
