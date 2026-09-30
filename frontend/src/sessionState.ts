import type { DisplayState, SessionState } from './types/api'

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

/**
 * What the user sees for a raw state. `session.state` events carry no
 * `display_state`, so the frontend derives it the same way the backend does.
 */
export function deriveDisplay(
  state: SessionState,
  finished: boolean,
  current?: DisplayState,
  cliRunning = false,
): { display_state: DisplayState; awaiting_decision: boolean } {
  if (state === 'connecting' || state === 'running') return { display_state: 'running', awaiting_decision: false }
  if (state === 'awaiting_decision') return { display_state: 'waiting', awaiting_decision: true }
  // Mirrors the backend: no client in the app, but the CLI is mid-turn.
  if (state === 'closed' && cliRunning) return { display_state: 'running', awaiting_decision: false }
  // A session the backend already shows as finished (marked, or idle for too long) stays so.
  const stays = finished || current === 'finished'
  return { display_state: stays ? 'finished' : 'waiting', awaiting_decision: false }
}
