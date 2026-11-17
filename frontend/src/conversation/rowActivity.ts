import type { Session } from '../types/api'
import { planVisible } from '../components/plan/planText'
import { waitingReason } from '../conversationList'
import { needsYou } from './needsYou'

export type ActivityKind = 'waiting' | 'plan' | 'command' | 'subagent' | 'action' | 'summary'

export interface RowActivity {
  kind: ActivityKind
  text: string
}

const COMMAND_PREFIX = 'Bash: '
const SUBAGENT_PREFIXES = ['Agent: ', 'Task: ']

/**
 * The one line a conversation row shows about what is going on: a request to the user, the plan task,
 * the last action while running, the short summary, or nothing.
 */
export function sessionActivity(session: Session): RowActivity | null {
  if (session.display_state === 'waiting' && needsYou(session)) {
    const reason = waitingReason(session)
    if (reason) return { kind: 'waiting', text: reason }
  }
  if (planVisible(session) && session.plan?.current) return { kind: 'plan', text: session.plan.current.title }
  if (session.display_state === 'running' && session.last_action) {
    const action = session.last_action
    if (action.startsWith(COMMAND_PREFIX)) return { kind: 'command', text: action.slice(COMMAND_PREFIX.length) }
    const prefix = SUBAGENT_PREFIXES.find((p) => action.startsWith(p))
    if (prefix) return { kind: 'subagent', text: action.slice(prefix.length) }
    return { kind: 'action', text: action }
  }
  if (session.digest_short) return { kind: 'summary', text: session.digest_short }
  return null
}
