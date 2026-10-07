import type { DeliveriesDay, Delivery } from './types/api'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** YYYY-MM-DD of a local date (today by default). */
export function localDay(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function parseDay(day: string): Date {
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
