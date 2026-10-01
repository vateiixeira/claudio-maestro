import type { Session } from '../types/api'

/** What decides whether a session wants the user: a pending decision, an error, or news not yet seen. */
export type NeedsYouFields = Pick<Session, 'unread' | 'state'> & { pending_kind?: string | null }

/** The one rule behind the orange: a pending decision (even before `pending_kind` arrives), an error, or something unread. */
export function needsYou(s: NeedsYouFields): boolean {
  return Boolean(s.pending_kind) || s.state === 'awaiting_decision' || s.state === 'error' || s.unread
}
