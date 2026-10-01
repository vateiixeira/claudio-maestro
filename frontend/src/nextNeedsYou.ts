import { inInbox } from './conversationList'
import type { Session } from './types/api'

/**
 * Conversations that wait for the user, other than `currentId`, in the order of the Inbox's
 * "Aguardando você" tab. `all` is the sessions store's list (most recent activity first).
 */
export function needsYouQueue(all: Session[], currentId: string | null | undefined): Session[] {
  return all.filter((s) => s.session_id !== currentId && inInbox(s, 'pede-voce'))
}

/**
 * The conversation the "next" action opens: the first of the "Aguardando você" list that comes after `currentId`
 * (same order as `all`), wrapping to the start at the end. When the current one is not on the list, the first.
 * Null when there is no other.
 */
export function nextNeedsYou(all: Session[], currentId: string | null | undefined): Session | null {
  const list = all.filter((s) => inInbox(s, 'pede-voce'))
  if (!list.some((s) => s.session_id !== currentId)) return null
  const at = list.findIndex((s) => s.session_id === currentId)
  for (let step = 1; step <= list.length; step++) {
    const candidate = list[(at + step) % list.length]
    if (candidate.session_id !== currentId) return candidate
  }
  return null
}
