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

/** "3 de 5": the current task over the total, or "Concluído" when the plan has no task left. */
export function planCount(plan: PlanSummary): string {
  return plan.current ? `${plan.current.number} de ${plan.total}` : 'Concluído'
}

/** Spoken form of the progress: "2 concluídas, 1 em andamento, 2 pendentes" (parts at zero are left out). */
export function planProgressText(plan: PlanSummary): string {
  const done = Math.max(0, plan.done)
  const running = plan.current ? 1 : 0
  const pending = Math.max(0, plan.total - done - running)
  const parts: string[] = []
  if (done || (!running && !pending)) parts.push(`${done} ${done === 1 ? 'concluída' : 'concluídas'}`)
  if (running) parts.push('1 em andamento')
  if (pending) parts.push(`${pending} ${pending === 1 ? 'pendente' : 'pendentes'}`)
  return parts.join(', ')
}
