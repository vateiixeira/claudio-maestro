import type { Session } from '../types/api'
import { hasRequest } from './marks'

/** What decides whether a session wants the user: a pending decision, an error, or news not yet seen. */
export type NeedsYouFields = Pick<Session, 'unread' | 'state'> & { pending_kind?: string | null; mark?: Session['mark'] }

/**
 * The one rule behind the orange: a real request from Claude (a pending decision, even before `pending_kind`
 * arrives, or an error), or something unread on a session with no mark. A marked session only wants you with a request.
 */
export function needsYou(s: NeedsYouFields): boolean {
  return hasRequest(s) || (s.unread && !s.mark)
}
