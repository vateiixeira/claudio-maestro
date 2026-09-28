/** Shows `path` relative to the home folder as `~/...` when it is inside it. */
export function tildePath(path: string, home: string | null): string {
  if (!home) return path
  if (path === home) return '~'
  if (path.startsWith(home + '/')) return '~' + path.slice(home.length)
  return path
}

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** Short Portuguese label for a Unix timestamp in seconds: "agora", "há 4 min", "ontem", "26 set". */
export function formatActivity(seconds: number, now: Date = new Date()): string {
  const date = new Date(seconds * 1000)
  const elapsed = (now.getTime() - date.getTime()) / 1000
  const today = startOfDay(now)
  const day = startOfDay(date)

  if (elapsed < 60) return 'agora'
  if (day === today) {
    if (elapsed < 3600) return `há ${Math.floor(elapsed / 60)} min`
    return `há ${Math.floor(elapsed / 3600)} h`
  }
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  if (day === yesterday) return 'ontem'
  const label = `${date.getDate()} ${MONTHS[date.getMonth()]}`
  return date.getFullYear() === now.getFullYear() ? label : `${label} ${date.getFullYear()}`
}
