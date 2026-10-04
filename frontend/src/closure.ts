import type { ClosureVerdict, Session } from './types/api'

export type ShownVerdict = Exclude<ClosureVerdict, 'in_progress'>

export const CLOSURE_LABELS: Record<ShownVerdict, string> = {
  can_close: 'Pode fechar',
  user_action: 'Falta ação sua',
  incomplete: 'Entrega incompleta',
}

export const CLOSURE_BADGE_CLASS: Record<ShownVerdict, string> = {
  can_close: 'border-primary/40 text-primary-soft',
  user_action: 'border-secondary/40 text-secondary-soft',
  incomplete: 'border-diff-del-fg/40 text-diff-del-fg',
}

export const CLOSURE_DOT_CLASS: Record<ShownVerdict, string> = {
  can_close: 'bg-primary',
  user_action: 'bg-secondary',
  incomplete: 'bg-diff-del-fg',
}

/** Verdict worth a badge: none for finished sessions, open work or a stale check. */
export function shownVerdict(session: Pick<Session, 'display_state' | 'closure_verdict'>): ShownVerdict | null {
  if (session.display_state === 'finished') return null
  const verdict = session.closure_verdict
  return verdict && verdict !== 'in_progress' ? verdict : null
}
