const DAY = 86400
const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

/** Path with the user's folder as `~` (`/home/<user>` or `/Users/<user>`); other paths stay as they are. */
export function shortPath(path: string): string {
  return path.replace(/^\/(?:home|Users)\/[^/]+(?=\/|$)/, '~')
}

function startOfDay(seconds: number): number {
  const date = new Date(seconds * 1000)
  return Math.floor(new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() / 1000)
}

/** A project is active today when it had activity since midnight or still has an open conversation. */
export function isActiveToday(latest: number, open: number, now: number): boolean {
  return open > 0 || (latest > 0 && latest >= startOfDay(now))
}

/** Whole days since the last activity when files are changed and the last use is over 2 days old; otherwise null. */
export function staleDays(changed: number, latest: number, now: number): number | null {
  if (changed <= 0 || latest <= 0 || now - latest <= 2 * DAY) return null
  return Math.floor((now - latest) / DAY)
}

/** "agora", "há 15 min", "há 3 h" today, "12 nov" on another day ("30 dez 2025" in another year), "sem uso" with no activity. */
export function activityText(latest: number, now: number): string {
  if (latest <= 0) return 'sem uso'
  const elapsed = now - latest
  if (elapsed < 60) return 'agora'
  if (elapsed < 3600) return `há ${Math.floor(elapsed / 60)} min`
  if (startOfDay(latest) === startOfDay(now)) return `há ${Math.floor(elapsed / 3600)} h`
  const date = new Date(latest * 1000)
  const label = `${date.getDate()} ${MONTHS[date.getMonth()]}`
  return date.getFullYear() === new Date(now * 1000).getFullYear() ? label : `${label} ${date.getFullYear()}`
}
