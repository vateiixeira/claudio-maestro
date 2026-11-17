import type { Run, RunOutcome } from '../../../types/org'

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const WEEKDAYS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado']
const two = (n: number) => String(n).padStart(2, '0')

/** The outcomes the "Problemas" filter keeps. */
export const PROBLEM_OUTCOMES: ReadonlySet<RunOutcome> = new Set<RunOutcome>(['failed', 'waiting', 'missed', 'skipped'])

/** A line of the list: one run, or the runs that were missed at the same minute (folded into one line). */
export type RunLine = { kind: 'run'; run: Run } | { kind: 'missed'; runs: Run[] }

const startOf = (line: RunLine): number => (line.kind === 'run' ? line.run.started_at : line.runs[0]!.started_at)

/** Folds the missed runs of the same minute into one line, keeping the order of the list (newest first). */
export function runLines(runs: Run[]): RunLine[] {
  const lines: RunLine[] = []
  const byMinute = new Map<number, Extract<RunLine, { kind: 'missed' }>>()
  for (const run of runs) {
    if (run.outcome !== 'missed') {
      lines.push({ kind: 'run', run })
      continue
    }
    const minute = Math.floor(run.started_at / 60)
    const known = byMinute.get(minute)
    if (known) {
      known.runs.push(run)
    } else {
      const line: Extract<RunLine, { kind: 'missed' }> = { kind: 'missed', runs: [run] }
      byMinute.set(minute, line)
      lines.push(line)
    }
  }
  return lines
}

/** "Hoje", "Ontem", "13 nov · sexta"; the year only when it is not the current one. */
export function dayLabel(seconds: number, now: Date): string {
  const d = new Date(seconds * 1000)
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (day === today.getTime()) return 'Hoje'
  if (day === new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1).getTime()) return 'Ontem'
  const year = d.getFullYear() === now.getFullYear() ? '' : ` ${d.getFullYear()}`
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year} · ${WEEKDAYS[d.getDay()]}`
}

function dayKey(seconds: number): string {
  const d = new Date(seconds * 1000)
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`
}

/** The lines grouped by local day, in the order they come (newest first). */
export function groupByDay(lines: RunLine[], now: Date): { key: string; label: string; lines: RunLine[] }[] {
  const groups: { key: string; label: string; lines: RunLine[] }[] = []
  for (const line of lines) {
    const key = dayKey(startOf(line))
    const last = groups[groups.length - 1]
    if (last && last.key === key) {
      last.lines.push(line)
    } else {
      groups.push({ key, label: dayLabel(startOf(line), now), lines: [line] })
    }
  }
  return groups
}

const COUNTED: { outcomes: RunOutcome[]; one: string; many: string }[] = [
  { outcomes: ['concluded', 'closed'], one: 'concluída', many: 'concluídas' },
  { outcomes: ['failed'], one: 'com falha', many: 'com falha' },
  { outcomes: ['waiting'], one: 'esperando você', many: 'esperando você' },
  { outcomes: ['missed'], one: 'perdida', many: 'perdidas' },
  { outcomes: ['skipped'], one: 'pulada', many: 'puladas' },
  { outcomes: ['cancelled'], one: 'cancelada', many: 'canceladas' },
]

function shortDate(d: Date, withYear: boolean): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${withYear ? ` ${d.getFullYear()}` : ''}`
}

/** "De 9 a 13 nov: 8 concluídas, 4 perdidas (...)." about the runs of the list; null when none ended. */
export function runsSummary(runs: Run[]): string | null {
  const parts: string[] = []
  const times: number[] = []
  for (const { outcomes, one, many } of COUNTED) {
    const mine = runs.filter((r) => outcomes.includes(r.outcome))
    if (mine.length === 0) continue
    parts.push(`${mine.length} ${mine.length === 1 ? one : many}`)
    times.push(...mine.map((r) => r.started_at))
  }
  if (parts.length === 0) return null
  const first = new Date(Math.min(...times) * 1000)
  const last = new Date(Math.max(...times) * 1000)
  const sameDay = dayKey(first.getTime() / 1000) === dayKey(last.getTime() / 1000)
  const sameMonth = first.getFullYear() === last.getFullYear() && first.getMonth() === last.getMonth()
  const crossYear = first.getFullYear() !== last.getFullYear()
  let range: string
  if (sameDay) range = `Em ${shortDate(last, false)}`
  else if (sameMonth) range = `De ${first.getDate()} a ${shortDate(last, false)}`
  else range = `De ${shortDate(first, crossYear)} a ${shortDate(last, crossYear)}`
  const missed = runs.some((r) => r.outcome === 'missed') ? ' (o horário passou sem o Maestro disparar o agente)' : ''
  return `${range}: ${parts.join(', ')}${missed}.`
}

/** The warning about agents that are off, or null when none is. */
export function offAgentsText(names: string[]): string | null {
  if (names.length === 0) return null
  if (names.length === 1) return `${names[0]} está desligado: nada dele roda até você ligar.`
  const list = `${names.slice(0, -1).join(', ')} e ${names[names.length - 1]}`
  return `${list} estão desligados: nada deles roda até você ligar.`
}

const SLOW_MIN_FACTOR = 3
const SLOW_MIN_SAMPLES = 4

const isDone = (run: Run): boolean => (run.outcome === 'concluded' || run.outcome === 'closed') && run.ended_at !== null
const durationOf = (run: Run): number => (run.ended_at ?? run.started_at) - run.started_at

/**
 * How many times longer a concluded run took than the usual one (the median of the others of its routine, or of
 * its agent when it has no routine). Null when it is not at least 3 times, or there are fewer than 4 to compare.
 */
export function slowFactor(run: Run, all: Run[]): { factor: number; scope: 'routine' | 'agent' } | null {
  if (!isDone(run)) return null
  const scope = run.routine_id !== null ? 'routine' : 'agent'
  const others = all.filter(
    (r) =>
      r.id !== run.id &&
      isDone(r) &&
      (scope === 'routine' ? r.routine_id === run.routine_id : r.agent_id === run.agent_id && r.routine_id === null),
  )
  if (others.length < SLOW_MIN_SAMPLES) return null
  const sorted = others.map(durationOf).sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const median = sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
  if (median <= 0) return null
  const factor = durationOf(run) / median
  return factor >= SLOW_MIN_FACTOR ? { factor: Math.round(factor), scope } : null
}

export function slowText(slow: { factor: number; scope: 'routine' | 'agent' }): string {
  return `Levou ${slow.factor} vezes mais que o normal ${slow.scope === 'routine' ? 'desta rotina' : 'deste agente'}`
}

/** The share, from 0 to 100, of the longest duration that the run took; 0 while it has not ended. */
export function durationShare(run: Run, maxSeconds: number): number {
  if (run.ended_at === null || maxSeconds <= 0) return 0
  return Math.min(100, Math.round((durationOf(run) / maxSeconds) * 100))
}
