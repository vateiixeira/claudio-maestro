import type { Session } from '../types/api'

/** What decides whether a session wants the user: a pending decision, an error, or news not yet seen. */
export type NeedsYouFields = Pick<Session, 'unread' | 'state'> & { pending_kind?: string | null }

/** The one rule behind the orange: a pending decision, an error, or something unread. */
export function needsYou(s: NeedsYouFields): boolean {
  return Boolean(s.pending_kind) || s.state === 'error' || s.unread
}
