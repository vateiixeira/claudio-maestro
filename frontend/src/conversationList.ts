import { shownVerdict } from './closure'
import { isDiscarded, markLane } from './conversation/marks'
import { needsYou } from './conversation/needsYou'
import type { Session } from './types/api'

/** Why a session waits for the user, or null when it does not wait. */
export function waitingReason(session: Session): string | null {
  if (session.display_state !== 'waiting') return null
  if (session.state === 'error') return 'Parou com erro'
  if (session.pending_kind === 'tool') return `Pede permissão: ${session.pending_permission?.tool_name ?? 'ferramenta'}`
  if (session.pending_kind === 'question') return 'Fez uma pergunta'
  if (session.pending_kind === 'plan') return 'Plano para aprovar'
  return 'Sua vez'
}

export type InboxTab = 'pede-voce' | 'nao-lidas' | 'em-execucao' | 'para-revisar' | 'pode-fechar' | 'depois' | 'todas'

export const INBOX_TABS: { id: InboxTab; label: string }[] = [
  { id: 'pede-voce', label: 'Aguardando você' },
  { id: 'nao-lidas', label: 'Não lidas' },
  { id: 'em-execucao', label: 'Em execução' },
  { id: 'para-revisar', label: 'Para revisar' },
  { id: 'pode-fechar', label: 'Pode fechar' },
  { id: 'depois', label: 'Depois' },
  { id: 'todas', label: 'Todas' },
]

export function isInboxTab(value: unknown): value is InboxTab {
  return INBOX_TABS.some((tab) => tab.id === value)
}

/** Whether a session shows in a Inbox tab. Finished and discarded sessions never do. */
export function inInbox(session: Session, tab: InboxTab): boolean {
  if (isDiscarded(session)) return false
  const waiting = session.display_state === 'waiting'
  const running = session.display_state === 'running'
  const open = session.display_state !== 'finished'
  const unread = session.unread && open
  const lane = markLane(session)
  if (tab === 'pede-voce') return waiting && needsYou(session) && lane === 'now'
  if (tab === 'nao-lidas') return unread && lane !== 'later'
  if (tab === 'em-execucao') return running
  if (tab === 'para-revisar') return open && lane === 'review'
  if (tab === 'pode-fechar') return shownVerdict(session) === 'can_close'
  if (tab === 'depois') return open && lane === 'later'
  return waiting || running || unread
}

export type DateLabel = 'Hoje' | 'Ontem' | 'Esta semana' | 'Antes'

function dayStart(year: number, month: number, day: number): number {
  return new Date(year, month, day).getTime()
}

/** Group of a Unix timestamp (seconds) by the local day. "Esta semana" only when `withWeek`. */
export function dateLabel(seconds: number, now: Date, withWeek: boolean): DateLabel {
  const time = seconds * 1000
  const y = now.getFullYear()
  const m = now.getMonth()
  const d = now.getDate()
  if (time >= dayStart(y, m, d)) return 'Hoje'
  if (time >= dayStart(y, m, d - 1)) return 'Ontem'
  if (withWeek && time >= dayStart(y, m, d - 6)) return 'Esta semana'
  return 'Antes'
}

const ORDER: DateLabel[] = ['Hoje', 'Ontem', 'Esta semana', 'Antes']

/** Sessions split by `dateLabel` of their last activity, keeping the list order. */
export function groupByDate(list: Session[], now: Date, withWeek: boolean): { label: DateLabel; sessions: Session[] }[] {
  const groups = new Map<DateLabel, Session[]>()
  for (const session of list) {
    const label = dateLabel(session.last_activity_at, now, withWeek)
    const bucket = groups.get(label) ?? []
    bucket.push(session)
    groups.set(label, bucket)
  }
  return ORDER.filter((label) => groups.has(label)).map((label) => ({ label, sessions: groups.get(label)! }))
}
