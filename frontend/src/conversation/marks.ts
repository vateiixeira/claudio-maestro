import type { Session, SessionMark } from '../types/api'

/** Where a session sits: now, waiting for a review, or later (on hold or blocked). */
export type MarkLane = 'now' | 'review' | 'later'

export const markLabels: Record<SessionMark, string> = {
  on_hold: 'Em espera',
  blocked: 'Bloqueada',
  review: 'Para revisar',
}

type LaneFields = Pick<Session, 'state'> & { mark?: SessionMark | null; pending_kind?: string | null }

/** A real request from Claude: a pending decision or an error. Unread news is not one. */
export function hasRequest(s: Pick<Session, 'state'> & { pending_kind?: string | null }): boolean {
  return Boolean(s.pending_kind) || s.state === 'awaiting_decision' || s.state === 'error'
}

/** A mark takes the session out of "now", unless Claude has a request. */
export function markLane(s: LaneFields): MarkLane {
  if (!s.mark || hasRequest(s)) return 'now'
  return s.mark === 'review' ? 'review' : 'later'
}

const seconds = (d: Date) => Math.floor(d.getTime() / 1000)

/** Tomorrow at 9:00, local time, in seconds. */
export function tomorrowAt9(now: Date): number {
  return seconds(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 9, 0, 0))
}

/** The next Monday after today at 9:00 (a week ahead when today is Monday), in seconds. */
export function nextMondayAt9(now: Date): number {
  const ahead = (8 - now.getDay()) % 7 || 7
  return seconds(new Date(now.getFullYear(), now.getMonth(), now.getDate() + ahead, 9, 0, 0))
}

const WEEKDAYS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']
const pad = (n: number) => String(n).padStart(2, '0')

/** "hoje", "amanhã", the weekday within 6 days, else "dd/mm". */
export function untilShort(until: number, now: Date): string {
  const d = new Date(until * 1000)
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((day(d) - day(now)) / 86_400_000)
  if (days === 0) return 'hoje'
  if (days === 1) return 'amanhã'
  if (days > 1 && days < 7) return WEEKDAYS[d.getDay()]!
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}

/** Text of the mark chip in the conversation header; null without a mark. */
export function markChipText(
  s: { mark?: SessionMark | null; mark_note?: string | null; mark_until?: number | null },
  now: Date,
): string | null {
  if (!s.mark) return null
  if (s.mark === 'on_hold') {
    if (!s.mark_until) return 'Em espera'
    const d = new Date(s.mark_until * 1000)
    return `Em espera até ${untilShort(s.mark_until, now)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  if (s.mark === 'blocked') return s.mark_note ? `Bloqueada: ${s.mark_note}` : 'Bloqueada'
  return 'Para revisar'
}
