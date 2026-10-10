const oneDecimal = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

/** Token count in words: "950", "84 mil", "1,5 mil", "1 milhão", "2,5 milhões". */
export function formatTokens(tokens: number): string {
  if (tokens < 1000) return String(Math.round(tokens))
  if (tokens < 1_000_000) return `${oneDecimal.format(tokens / 1000)} mil`
  const millions = Math.round((tokens / 1_000_000) * 10) / 10
  return `${oneDecimal.format(millions)} ${millions === 1 ? 'milhão' : 'milhões'}`
}

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
  // Under an hour stays in minutes even across midnight: "ontem" for 42 minutes ago reads wrong.
  if (elapsed < 3600) return `há ${Math.floor(elapsed / 60)} min`
  if (day === today) return `há ${Math.floor(elapsed / 3600)} h`
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  if (day === yesterday) return 'ontem'
  const label = `${date.getDate()} ${MONTHS[date.getMonth()]}`
  return date.getFullYear() === now.getFullYear() ? label : `${label} ${date.getFullYear()}`
}

/** Compact time since `seconds` (Unix), for tight spots like the sidebar: "agora", "3 min", "1 h", "1 dia", "4 dias". */
export function formatElapsedShort(seconds: number, nowMs: number = Date.now()): string {
  const elapsed = Math.floor(nowMs / 1000 - seconds)
  if (elapsed < 60) return 'agora'
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)} min`
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)} h`
  const days = Math.floor(elapsed / 86400)
  return days === 1 ? '1 dia' : `${days} dias`
}

/** How long something has been running, to the second: "12 s", "1 min 3 s", "1 h 5 min". */
export function formatRunningTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  if (total < 60) return `${total} s`
  if (total < 3600) {
    const rest = total % 60
    return rest ? `${Math.floor(total / 60)} min ${rest} s` : `${Math.floor(total / 60)} min`
  }
  const minutes = Math.floor((total % 3600) / 60)
  return minutes ? `${Math.floor(total / 3600)} h ${minutes} min` : `${Math.floor(total / 3600)} h`
}

const MODEL_FAMILIES = ['sonnet', 'opus', 'haiku']
const capitalize = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)

/**
 * A model id as people say it: "claude-sonnet-5-5" -> "Sonnet 5.5", "claude-haiku-4-5-20251001"
 * -> "Haiku 4.5", "claude-opus-4-7[1m]" -> "Opus 4.7 (1M)", the alias "opus" -> "Opus".
 * An id it does not recognize comes back as it is.
 */
export function formatModelName(model: string): string {
  const context = /\[(\d+m)\]$/i.exec(model.trim())
  const suffix = context ? ` (${context[1]!.toUpperCase()})` : ''
  const id = model.trim().toLowerCase().replace(/\[[^\]]*\]$/, '').replace(/^claude-/, '').replace(/-\d{8}$/, '')
  if (MODEL_FAMILIES.includes(id)) return capitalize(id) + suffix
  // "sonnet-5-5", "opus-4-7"
  const current = /^(sonnet|opus|haiku)-(\d+)(?:-(\d+))?$/.exec(id)
  if (current) return `${capitalize(current[1]!)} ${current[3] ? `${current[2]}.${current[3]}` : current[2]}${suffix}`
  // "3-5-sonnet", "3-opus"
  const legacy = /^(\d+)(?:-(\d+))?-(sonnet|opus|haiku)$/.exec(id)
  if (legacy) return `${capitalize(legacy[3]!)} ${legacy[2] ? `${legacy[1]}.${legacy[2]}` : legacy[1]}${suffix}`
  return model
}
