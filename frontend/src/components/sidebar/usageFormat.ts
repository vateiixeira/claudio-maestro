const WEEKDAYS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']
const DAY_MS = 86_400_000

const pad = (n: number) => String(n).padStart(2, '0')
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

/** "21:30" today (or already past), "seg 19:00" within 6 days, "12/10 19:00" further; local time. */
export function formatReset(resetsAt: number | null, now: number): string {
  if (resetsAt === null) return ''
  const when = new Date(resetsAt * 1000)
  const time = `${pad(when.getHours())}:${pad(when.getMinutes())}`
  const days = Math.round((startOfDay(when) - startOfDay(new Date(now))) / DAY_MS)
  if (days <= 0) return time
  if (days < 7) return `${WEEKDAYS[when.getDay()]} ${time}`
  return `${pad(when.getDate())}/${pad(when.getMonth() + 1)} ${time}`
}

/** "às 21:30" for a bare time; the day forms read fine as they are ("renova seg 19:00"). */
export function resetPhrase(formatted: string): string {
  return formatted.includes(' ') ? formatted : `às ${formatted}`
}

/** Fill color of the bar: green, amber when the server warns, red when critical. */
export function severityClass(severity: string): string {
  if (severity === 'critical') return 'bg-diff-del-fg'
  if (severity === 'warning') return 'bg-secondary'
  return 'bg-primary'
}
