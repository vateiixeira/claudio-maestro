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

/** Moves `id` to the front, without duplicates, keeping at most RECENT_MAX. */
export function noteOpened(id: string): string[] {
  const ids = [id, ...readRecent().filter((other) => other !== id)].slice(0, RECENT_MAX)
  recentIds.value = ids
  try {
    localStorage.setItem(KEY, JSON.stringify(ids))
  } catch {
    // Without storage the history lasts only for this page.
  }
  return ids
}
