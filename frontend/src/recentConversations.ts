import { ref } from 'vue'

const KEY = 'vibing:recent-conversations'
export const RECENT_MAX = 20

/** Ids of conversations the user opened, most recent first (empty if storage fails). */
export function readRecent(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    if (Array.isArray(parsed) && parsed.every((id) => typeof id === 'string')) return parsed
  } catch {
    // Unreadable storage or invalid JSON: treat as no history.
  }
  return []
}

/** Shared so the sidebar updates the moment a conversation is opened. */
export const recentIds = ref<string[]>(readRecent())

/** How many recent conversations the sidebar shows. */
export const RECENT_VISIBLE = 5

/** Ids the sidebar is showing under "Recentes" right now (it writes them). */
export const shownRecentIds = ref<string[]>([])

function save(ids: string[]): string[] {
  recentIds.value = ids
  try {
    localStorage.setItem(KEY, JSON.stringify(ids))
  } catch {
    // Without storage the history lasts only for this page.
  }
  return ids
}

/**
 * A conversation was opened. One already shown under "Recentes" keeps its place, so
 * clicking down the list does not reshuffle it; any other goes to the front.
 */
export function noteOpened(id: string): string[] {
  const current = readRecent()
  if (shownRecentIds.value.includes(id) && current.includes(id)) {
    recentIds.value = current
    return current
  }
  return save([id, ...current.filter((other) => other !== id)].slice(0, RECENT_MAX))
}

/** A conversation started running (in the app or elsewhere): listed once, at the front. */
export function noteRunning(id: string): string[] {
  const current = readRecent()
  if (current.includes(id)) return current
  return save([id, ...current].slice(0, RECENT_MAX))
}
