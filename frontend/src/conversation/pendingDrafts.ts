import type { DraftImage } from './images'

export interface PendingDraft {
  text: string
  error: string | null
  /** Images that were attached to the first prompt. */
  images?: DraftImage[]
}

// Text to put in a composer that opens next: a first prompt that could not be sent.
const drafts = new Map<string, PendingDraft>()

export function setPendingDraft(sessionId: string, draft: PendingDraft): void {
  drafts.set(sessionId, draft)
}

/** The draft for this session, removed on read (it fills one composer once). */
export function takePendingDraft(sessionId: string): PendingDraft | null {
  const draft = drafts.get(sessionId) ?? null
  drafts.delete(sessionId)
  return draft
}
