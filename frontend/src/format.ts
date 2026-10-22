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

/** When a context breakdown was measured, from a Unix timestamp in seconds: "Medido às 14:32" (today) or "Medido em 21 out às 14:32". */
export function formatMeasuredAt(seconds: number, now: Date = new Date()): string {
  const date = new Date(seconds * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (startOfDay(date) === startOfDay(now)) return `Medido às ${time}`
  return `Medido em ${date.getDate()} ${MONTHS[date.getMonth()]} às ${time}`
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

/** Short aliases the CLI accepts; they are the only families recognized without the "claude-" prefix. */
const MODEL_ALIASES = ['sonnet', 'opus', 'haiku', 'fable']
const capitalize = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)

/**
 * A model id as people say it: "claude-sonnet-5-5" -> "Sonnet 5.5", "claude-haiku-4-5-20251001"
 * -> "Haiku 4.5", "claude-opus-4-7[1m]" -> "Opus 4.7 (1M)", the alias "opus" -> "Opus".
 *
 * The family is any lowercase word, so a new one ("claude-fable-5-1" -> "Fable 5.1") needs no
 * change here. To keep unrelated ids intact, a family outside the known aliases (sonnet, opus,
 * haiku, fable) is only accepted when the id starts with "claude-" AND carries a version:
 * "claude-foo" or "claude-foo-20251001" (no version), "gpt-5", "my-model-1" and "gpt-4o" (no
 * "claude-") all come back as they are, and so do "", "inherit" and "<synthetic>".
 */
export function formatModelName(model: string): string {
  const context = /\[(\d+m)\]$/i.exec(model.trim())
  const suffix = context ? ` (${context[1]!.toUpperCase()})` : ''
  const lowered = model.trim().toLowerCase().replace(/\[[^\]]*\]$/, '')
  const claudePrefixed = lowered.startsWith('claude-')
  const id = lowered.replace(/^claude-/, '').replace(/-\d{8}$/, '')
  const accepts = (family: string) => claudePrefixed || MODEL_ALIASES.includes(family)
  if (MODEL_ALIASES.includes(id)) return capitalize(id) + suffix
  // "sonnet-5-5", "fable-5-1"
  const current = /^([a-z]+)-(\d+)(?:-(\d+))?$/.exec(id)
  if (current && accepts(current[1]!)) {
    return `${capitalize(current[1]!)} ${current[3] ? `${current[2]}.${current[3]}` : current[2]}${suffix}`
  }
  // "3-5-sonnet", "3-opus"
  const legacy = /^(\d+)(?:-(\d+))?-([a-z]+)$/.exec(id)
  if (legacy && accepts(legacy[3]!)) {
    return `${capitalize(legacy[3]!)} ${legacy[2] ? `${legacy[1]}.${legacy[2]}` : legacy[1]}${suffix}`
  }
  return model
}
