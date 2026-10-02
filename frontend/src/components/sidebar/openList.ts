import { needsYou } from '../../conversation/needsYou'
import type { Session } from '../../types/api'

/** How many rows "Abertas" shows before "Ver todas". */
export const OPEN_MAX = 8

function band(s: Session): number {
  if (s.display_state === 'waiting' && needsYou(s)) return 0
  if (s.display_state === 'running') return 1
  return 2
}

/**
 * Conversations not finished, for the sidebar's "Abertas": first what waits for you, then what is
 * running, then the rest. `all` comes newest first and the sort is stable, so each band keeps that order.
 */
export function openSessions(all: Session[]): Session[] {
  return all.filter((s) => s.display_state !== 'finished').sort((a, b) => band(a) - band(b))
}

/**
 * Open conversations of one project that sit outside its groups (those show under their group),
 * in "Abertas" order. A session whose group no longer exists counts as loose.
 */
export function looseOpenSessions(all: Session[], projectId: number, groupIds: ReadonlySet<number>): Session[] {
  return openSessions(all.filter((s) => s.project_id === projectId && (s.group_id == null || !groupIds.has(s.group_id))))
}
