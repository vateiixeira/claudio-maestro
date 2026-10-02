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
