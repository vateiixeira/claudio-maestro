import type { PlanSummary, Session } from '../../types/api'

/** "Tarefa 4 de 12: título", or "Concluído" when the plan has no task left. */
export function planPosition(plan: PlanSummary): string {
  return plan.current ? `Tarefa ${plan.current.number} de ${plan.total}: ${plan.current.title}` : 'Concluído'
}

/** "4/12": the current task over the total ("12/12" when done). */
export function planBadge(plan: PlanSummary): string {
  return plan.current ? `${plan.current.number}/${plan.total}` : `${plan.total}/${plan.total}`
}

/** The strip shows only for a plan still in progress on a conversation that is not finished. */
export function planVisible(session: Pick<Session, 'plan' | 'finished' | 'display_state'>): boolean {
  return !!session.plan && !session.finished && session.display_state !== 'finished' && !!session.plan.current
}

/** True while nothing is running the conversation (neither the app nor the CLI): the strip shows "parado". */
export function planStopped(session: Pick<Session, 'display_state' | 'cli_running'>): boolean {
  return session.display_state !== 'running' && !session.cli_running
}
