import { needsYou } from './conversation/needsYou'
import type { DisplayState, Session, SessionState } from './types/api'

export const sessionStateLabels: Record<SessionState, string> = {
  closed: 'Fechada',
  connecting: 'Conectando',
  running: 'Rodando',
  awaiting_decision: 'Aguardando você',
  idle: 'Parada',
  error: 'Erro',
}

/** Shape shown next to a session: circle while it works, triangle when it needs the user. */
export type StateShape = 'circle' | 'triangle' | 'none'

export function stateShape(state: SessionState): StateShape {
  if (state === 'running' || state === 'connecting') return 'circle'
  if (state === 'awaiting_decision' || state === 'error') return 'triangle'
  return 'none'
}

export const displayStateLabels: Record<DisplayState, string> = {
  running: 'Em execução',
  waiting: 'Aguardando você',
  finished: 'Finalizada',
}

/** Spoken/written label of a session's display state: a plain wait is "Sua vez", one that needs the user "Aguardando você". */
export function displayStateLabel(
  session: Pick<Session, 'display_state' | 'unread' | 'state'> & { pending_kind?: string | null; interrupted?: boolean; mark?: Session['mark'] },
): string {
  if (session.interrupted && session.display_state !== 'running') return 'Interrompida'
  if (session.display_state === 'waiting' && !needsYou(session)) return 'Sua vez'
  return displayStateLabels[session.display_state]
}

/**
 * What the user sees for a raw state. `session.state` events carry no
 * `display_state`, so the frontend derives it the same way the backend does.
 */
export function deriveDisplay(
  state: SessionState,
  finished: boolean,
  current?: DisplayState,
  cliRunning = false,
  subagentsRunning = false,
): { display_state: DisplayState; awaiting_decision: boolean } {
  if (state === 'connecting' || state === 'running') return { display_state: 'running', awaiting_decision: false }
  if (state === 'awaiting_decision') return { display_state: 'waiting', awaiting_decision: true }
  // Mirrors the backend: no client in the app, but the CLI is mid-turn.
  if (state === 'closed' && cliRunning) return { display_state: 'running', awaiting_decision: false }
  // Mirrors the backend: the main turn ended, but a subagent of the client still works.
  if (state === 'idle' && subagentsRunning) return { display_state: 'running', awaiting_decision: false }
  // A session the backend already shows as finished (marked, or idle for too long) stays so.
  const stays = finished || current === 'finished'
  return { display_state: stays ? 'finished' : 'waiting', awaiting_decision: false }
}
