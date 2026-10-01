import { inInbox } from './conversationList'
import type { Session } from './types/api'

/**
 * Conversations that wait for the user, other than `currentId`, in the order of the Inbox's
 * "Aguardando você" tab. `all` is the sessions store's list (most recent activity first).
 */
export function needsYouQueue(all: Session[], currentId: string | null | undefined): Session[] {
  return all.filter((s) => s.session_id !== currentId && inInbox(s, 'pede-voce'))
}
