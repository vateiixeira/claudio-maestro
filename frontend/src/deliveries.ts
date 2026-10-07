import type { DeliveriesDay, Delivery } from './types/api'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** YYYY-MM-DD of a local date (today by default). */
export function localDay(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function parseDay(day: string): Date {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(y!, m! - 1, d!)
}

export function shiftDay(day: string, delta: number): string {
  const d = parseDay(day)
  d.setDate(d.getDate() + delta)
  return localDay(d)
}

const longDay = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' })
const time = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })

export function formatDayLong(day: string): string {
  const text = longDay.format(parseDay(day))
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function formatTime(ts: number): string {
  return time.format(new Date(ts * 1000))
}

export function deliveryTitle(d: Delivery): string {
  return d.summary_title || d.title
}

export function groupByProject(list: Delivery[]): { project: string; items: Delivery[] }[] {
  const groups: { project: string; items: Delivery[] }[] = []
  for (const d of list) {
    let group = groups.find((g) => g.project === d.project_name)
    if (!group) groups.push((group = { project: d.project_name, items: [] }))
    group.items.push(d)
  }
  return groups
}

export function deliveriesMarkdown(day: DeliveriesDay): string {
  const lines = [`## ${formatDayLong(day.date)}`, '']
  if (!day.deliveries.length && !day.in_progress.length) {
    lines.push('Nada finalizado neste dia.')
  }
  for (const group of groupByProject(day.deliveries)) {
    lines.push(`### ${group.project}`)
    group.items.forEach((d, i) => {
      if (i > 0) lines.push('')
      lines.push(`**${deliveryTitle(d)}**`, ...d.bullets.map((b) => `- ${b}`))
    })
    lines.push('')
  }
  if (day.in_progress.length) {
    lines.push('### Em andamento', ...day.in_progress.map((s) => `- ${s.project_name}: ${s.title}`), '')
  }
  return lines.join('\n').replace(/\n+$/, '') + '\n'
}

/** Markdown of one project's records for the day: the day header, the project and its records, no "in progress". */
export function projectMarkdown(day: DeliveriesDay, project: string): string {
  return deliveriesMarkdown({ ...day, deliveries: day.deliveries.filter((d) => d.project_name === project), in_progress: [] })
}

const RULER_ROWS = 3
// Marks closer than this (percent of the ruler) would overlap, so the next one goes to another row.
const RULER_MIN_GAP = 1.5

export interface RulerMark {
  id: number
  /** Position along the ruler, in percent. */
  left: number
  /** Stacking level, 0 (on the line) up to 2. */
  row: number
}

export interface RulerLayout {
  startHour: number
  endHour: number
  marks: RulerMark[]
}

const minutesOfDay = (ts: number): number => {
  const d = new Date(ts * 1000)
  return d.getHours() * 60 + d.getMinutes()
}

/**
 * The day ruler: whole hours from the one before the first record to the one after the last (at least 2 hours),
 * and each record as a mark placed by its time. Close marks stack in up to 3 rows so they do not cover each other.
 */
export function rulerLayout(list: Delivery[]): RulerLayout {
  if (!list.length) return { startHour: 0, endHour: 0, marks: [] }
  const items = list.map((d) => ({ id: d.id, minutes: minutesOfDay(d.finished_at) })).sort((a, b) => a.minutes - b.minutes || a.id - b.id)
  let startHour = Math.floor(items[0]!.minutes / 60)
  let endHour = Math.floor(items[items.length - 1]!.minutes / 60) + 1
  if (endHour - startHour < 2) endHour = startHour + 2
  if (endHour > 24) {
    endHour = 24
    startHour = 22
  }
  const span = (endHour - startHour) * 60
  const lastLeft: number[] = Array(RULER_ROWS).fill(-Infinity)
  const marks = items.map(({ id, minutes }) => {
    const left = ((minutes - startHour * 60) / span) * 100
    let row = lastLeft.findIndex((last) => left - last >= RULER_MIN_GAP)
    if (row < 0) row = lastLeft.indexOf(Math.min(...lastLeft))
    lastLeft[row] = left
    return { id, left, row }
  })
  return { startHour, endHour, marks }
}
