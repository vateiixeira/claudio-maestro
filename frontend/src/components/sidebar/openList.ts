import { isDiscarded, markLane } from '../../conversation/marks'
import { needsYou } from '../../conversation/needsYou'
import type { Session } from '../../types/api'

function band(s: Session): number {
  if (s.display_state === 'waiting' && needsYou(s)) return 0
  if (s.priority) return 1
  if (s.display_state === 'running') return 2
  return 3
}

/**
 * Conversations not finished nor discarded, in the order the sidebar lists them: first what waits for you, then what is
 * marked as a priority, then what is running, then the rest. `all` comes newest first and the sort is stable, so each band keeps that order.
 */
export function openSessions(all: Session[]): Session[] {
  return all.filter((s) => s.display_state !== 'finished' && !isDiscarded(s)).sort((a, b) => band(a) - band(b))
}

/** Open conversations of the "Para revisar" or "Depois" lane, in that order. */
export function laneSessions(all: Session[], lane: 'review' | 'later'): Session[] {
  return openSessions(all).filter((s) => markLane(s) === lane)
}

/**
 * Open conversations of one project that sit outside its groups (those show under their group),
 * in that order. A session whose group no longer exists counts as loose.
 */
export function looseOpenSessions(all: Session[], projectId: number, groupIds: ReadonlySet<number>): Session[] {
  return openSessions(all.filter((s) => s.project_id === projectId && (s.group_id == null || !groupIds.has(s.group_id))))
}
