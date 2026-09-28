import type { SessionState } from './types/api'

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
