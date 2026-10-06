import type { DraftImage } from './images'

// What was typed in the message box of each session, so switching sessions never loses it.
// Text goes to localStorage (survives reload); images stay in memory only, because their
// data URLs are too big for localStorage.

const PREFIX = 'maestro:composer-draft:'

const texts = new Map<string, string>()
const images = new Map<string, DraftImage[]>()

/** The saved text of the session, or an empty string. */
export function loadDraftText(sessionId: string): string {
  try {
    const stored = localStorage.getItem(PREFIX + sessionId)
    if (stored !== null) return stored
  } catch {
    // Without storage the draft lives only while the page is open.
  }
  return texts.get(sessionId) ?? ''
}

/** Saves the text; an empty text removes the draft. */
export function saveDraftText(sessionId: string, text: string): void {
  if (text === '') {
    texts.delete(sessionId)
    try {
      localStorage.removeItem(PREFIX + sessionId)
    } catch {
      // Nothing to remove.
    }
    return
  }
  texts.set(sessionId, text)
  try {
    localStorage.setItem(PREFIX + sessionId, text)
  } catch {
    // The in-memory copy is enough while the page is open.
  }
}

export function loadDraftImages(sessionId: string): DraftImage[] {
  return [...(images.get(sessionId) ?? [])]
}

export function saveDraftImages(sessionId: string, list: DraftImage[]): void {
  if (list.length) images.set(sessionId, [...list])
  else images.delete(sessionId)
}

/** For tests: forgets every draft, in memory and in storage. */
export function resetComposerDrafts(): void {
  texts.clear()
  images.clear()
  try {
    for (const key of Object.keys(localStorage)) if (key.startsWith(PREFIX)) localStorage.removeItem(key)
  } catch {
    // No storage, nothing to reset.
  }
}
