import { isActive } from './groupList'
import type { Session } from './types/api'
import type { Agent, RunOutcome, TaskPriority, TaskStatus, WakeSource } from './types/org'

// Labels and shapes of the organization of agents. A state always has a shape besides its color.

/** `SLUG_MAX_LENGTH` of `org/files.py`. */
export const SLUG_MAX_LENGTH = 40
/** `MEMORY_MAX_CHARS` of `org/files.py`. */
export const MEMORY_MAX = 4000
/** `DEFINITION_MAX_BYTES` of `org/definition.py`. */
export const DEFINITION_MAX_BYTES = 100_000

/** ISO weekdays 1 (Monday) to 7 (Sunday): the button letter and the short name. */
export const DAYS = [
  { digit: '1', letter: 'S', short: 'seg', name: 'segunda' },
  { digit: '2', letter: 'T', short: 'ter', name: 'terça' },
  { digit: '3', letter: 'Q', short: 'qua', name: 'quarta' },
  { digit: '4', letter: 'Q', short: 'qui', name: 'quinta' },
  { digit: '5', letter: 'S', short: 'sex', name: 'sexta' },
  { digit: '6', letter: 'S', short: 'sáb', name: 'sábado' },
  { digit: '7', letter: 'D', short: 'dom', name: 'domingo' },
] as const

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'A fazer',
  in_progress: 'Em andamento',
  in_review: 'Em revisão',
  blocked: 'Bloqueada',
  done: 'Concluída',
  cancelled: 'Cancelada',
}

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  urgent: 'Urgente',
  high: 'Alta',
  normal: 'Normal',
  low: 'Baixa',
}

export type AgentState = 'idle' | 'busy' | 'waiting' | 'off'

export const AGENT_STATE_LABELS: Record<AgentState, string> = {
  idle: 'Ocioso',
  busy: 'Executando',
  waiting: 'Aguardando você',
  off: 'Desligado',
}

export const OUTCOME_LABELS: Record<RunOutcome, string> = {
  starting: 'Iniciando',
  running: 'Rodando',
  concluded: 'Concluída',
  closed: 'Fechada',
  waiting: 'Esperando você',
  failed: 'Falhou',
  skipped: 'Pulada',
  missed: 'Perdida',
  cancelled: 'Cancelada',
}

/** What woke the agent up. */
export const SOURCE_LABELS: Record<WakeSource, string> = {
  routine: 'Rotina',
  message: 'Mensagem',
  assignment: 'Tarefa',
  comment: 'Comentário',
  decision: 'Decisão',
  manual: 'Manual',
}

export type StateShape = 'circle' | 'spinner' | 'triangle' | 'check' | 'cross' | 'dash'

export function outcomeShape(outcome: RunOutcome): StateShape {
  switch (outcome) {
    case 'starting':
    case 'running': return 'spinner'
    case 'concluded':
    case 'closed': return 'check'
    case 'waiting': return 'triangle'
    case 'failed': return 'cross'
    default: return 'dash'
  }
}

export function taskStatusShape(status: TaskStatus): StateShape {
  switch (status) {
    case 'todo': return 'circle'
    case 'in_progress': return 'spinner'
    case 'in_review': return 'triangle'
    case 'blocked': return 'cross'
    case 'done': return 'check'
    case 'cancelled': return 'dash'
  }
}

function asksForYou(session: Session): boolean {
  return isActive(session) && (Boolean(session.pending_kind) || session.state === 'awaiting_decision')
}

/**
 * The state of an agent for the tree and the badges. Off wins over everything; then waiting for you (the main
 * conversation asks for an ok or an answer, or the last run waits); then running; otherwise idle.
 */
export function agentState(
  agent: Pick<Agent, 'enabled' | 'busy' | 'main_session_id' | 'last_run'>,
  sessions: Session[],
): AgentState {
  if (!agent.enabled) return 'off'
  const main = agent.main_session_id ? sessions.find((s) => s.session_id === agent.main_session_id) : undefined
  if ((main && asksForYou(main)) || agent.last_run?.outcome === 'waiting') return 'waiting'
  if (agent.busy) return 'busy'
  return 'idle'
}
