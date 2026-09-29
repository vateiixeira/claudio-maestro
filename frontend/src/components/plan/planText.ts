import type { PlanSummary, Session } from '../../types/api'

export function planPosition(plan: PlanSummary): string {
  return plan.current ? `Tarefa ${plan.current.number} de ${plan.total}: ${plan.current.title}` : 'Concluído'
}

export function planBadge(plan: PlanSummary): string {
  return plan.current ? `${plan.current.number}/${plan.total}` : `${plan.total}/${plan.total}`
}

export function planVisible(session: Pick<Session, 'plan' | 'finished' | 'display_state'>): boolean {
  return !!session.plan && !session.finished && session.display_state !== 'finished' && !!session.plan.current
}

export function planStopped(session: Pick<Session, 'display_state'>): boolean {
  return session.display_state !== 'running'
}
