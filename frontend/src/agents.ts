import type { SpecialistRunOutcome, SpecialistSchedule } from './types/api'

// Mirrors `OUTWARD_DEFAULTS` and `ALWAYS_DEFAULTS` of `backend/claudio_maestro/specialists/policy.py`:
// the API only returns the patterns a person added, the factory ones are always in force.
export const OUTWARD_DEFAULTS = ['git push', 'gh pr create', 'gh pr merge', 'gh issue comment', 'gh issue close', 'gh release'] as const
export const ALWAYS_DEFAULTS = ['gh pr merge'] as const

/** `LEARNINGS_MAX_CHARS` of the backend. */
export const LEARNINGS_MAX = 4000
/** `SLUG_MAX_LENGTH` of the backend. */
export const SLUG_MAX_LENGTH = 40

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

export const OUTCOME_LABELS: Record<SpecialistRunOutcome, string> = {
  running: 'Rodando',
  concluded: 'Concluída',
  closed: 'Fechada',
  waiting: 'Esperando você',
  failed: 'Falhou',
  skipped: 'Pulada',
  missed: 'Perdida',
}

export type OutcomeShape = 'spinner' | 'check' | 'triangle' | 'cross' | 'dash'

export function outcomeShape(outcome: SpecialistRunOutcome): OutcomeShape {
  switch (outcome) {
    case 'running': return 'spinner'
    case 'concluded':
    case 'closed': return 'check'
    case 'waiting': return 'triangle'
    case 'failed': return 'cross'
    default: return 'dash'
  }
}

/** The next slot of the schedules ("próximo: seg 08:40"), or why there is none. */
export function nextRunLabel(schedules: SpecialistSchedule[], enabled: boolean, now: Date = new Date()): string {
  if (schedules.length === 0) return 'sem horário'
  if (!enabled) return 'horários desligados'
  let best: { at: number; iso: number; time: string } | null = null
  for (let offset = 0; offset <= 7; offset++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
    const iso = ((day.getDay() + 6) % 7) + 1
    for (const schedule of schedules) {
      if (!schedule.days.includes(String(iso))) continue
      const [h, m] = schedule.time.split(':').map(Number)
      const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h ?? 0, m ?? 0).getTime()
      if (at > now.getTime() && (!best || at < best.at)) best = { at, iso, time: schedule.time }
    }
    if (best) break
  }
  if (!best) return 'sem horário'
  return `próximo: ${DAYS[best.iso - 1]!.short} ${best.time}`
}

/** Suggestion for the folder name: lowercase letters, digits and single hyphens. */
export function slugify(name: string): string {
  const slug = name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, SLUG_MAX_LENGTH)
  return slug.replace(/-+$/g, '')
}

/** Turns one weekday digit on or off in a "135"-style string, keeping the digits sorted. */
export function toggleDay(days: string, digit: string): string {
  const set = new Set(days.split('').filter(Boolean))
  if (set.has(digit)) set.delete(digit)
  else set.add(digit)
  return [...set].sort().join('')
}

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const two = (n: number) => String(n).padStart(2, '0')

/** "26 out 14:05" for a Unix timestamp in seconds, with the year when it is not the current one. */
export function formatRunDate(seconds: number, now: Date = new Date()): string {
  const d = new Date(seconds * 1000)
  const year = d.getFullYear() === now.getFullYear() ? '' : ` ${d.getFullYear()}`
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year} ${two(d.getHours())}:${two(d.getMinutes())}`
}

/** Only http and https become links; anything else (a `javascript:` URL, a path) stays text. */
export function safeLink(link: string | null): string | null {
  if (!link) return null
  try {
    const url = new URL(link)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

const thousands = new Intl.NumberFormat('pt-BR')
export const formatCount = (n: number) => thousands.format(n)
