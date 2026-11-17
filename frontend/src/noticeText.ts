/** The headline and the rest of what an agent notice says, for the Inbox's "Novidades" list. */

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const WEEKDAYS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado']

const plain = (text: string) => text.replace(/\*\*/g, '')

/** The first non-empty line is the headline; the other lines, joined by a space, are the body. No bold markers. */
export function noticeParts(text: string): { headline: string; body: string } {
  const lines = plain(text).split('\n').map((l) => l.trim()).filter(Boolean)
  return { headline: lines[0] ?? '', body: lines.slice(1).join(' ') }
}

/** What comes after the headline, with its paragraphs kept (at most one blank line between them). */
export function noticeFullBody(text: string): string {
  const lines = plain(text).split('\n').map((l) => l.trim())
  const start = lines.findIndex((l) => l !== '')
  if (start === -1) return ''
  return lines.slice(start + 1).join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

/** "Hoje", "Ontem", "13 nov · sexta" or, in another year, "30 dez 2025 · terça" (local days). */
export function noticeDayLabel(seconds: number, now: Date): string {
  const date = new Date(seconds * 1000)
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  if (day === today) return 'Hoje'
  if (day === yesterday) return 'Ontem'
  const year = date.getFullYear() === now.getFullYear() ? '' : ` ${date.getFullYear()}`
  return `${date.getDate()} ${MONTHS[date.getMonth()]}${year} · ${WEEKDAYS[date.getDay()]}`
}
