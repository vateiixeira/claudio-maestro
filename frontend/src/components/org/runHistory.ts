import type { Run } from '../../types/org'

/** One bar of the history: concluded, failed, waiting for the person, or a run that did not happen. */
export type HistoryBar = 'ok' | 'fail' | 'wait' | 'miss'

/** How many bars the history shows. */
export const HISTORY_MAX = 14

const KIND: Partial<Record<Run['outcome'], HistoryBar>> = {
  concluded: 'ok',
  closed: 'ok',
  failed: 'fail',
  waiting: 'wait',
  missed: 'miss',
  skipped: 'miss',
  cancelled: 'miss',
}

/**
 * The bars of the last runs that ended, oldest first. `runs` comes newest first, as the store keeps it; runs
 * that are starting or running are not part of the history yet.
 */
export function historyBars(runs: Run[], max: number = HISTORY_MAX): HistoryBar[] {
  const bars: HistoryBar[] = []
  for (const run of runs) {
    const kind = KIND[run.outcome]
    if (kind === undefined) continue
    bars.push(kind)
    if (bars.length === max) break
  }
  return bars.reverse()
}

const PARTS: [HistoryBar, string, string][] = [
  ['ok', 'concluída', 'concluídas'],
  ['fail', 'com falha', 'com falha'],
  ['wait', 'esperando você', 'esperando você'],
  ['miss', 'perdida', 'perdidas'],
]

/** "Últimas 4 execuções: 2 concluídas, 1 com falha, 1 perdida": the text for a screen reader. */
export function historyLabel(bars: HistoryBar[]): string {
  if (bars.length === 0) return ''
  const counts = PARTS.flatMap(([kind, one, many]) => {
    const n = bars.filter((b) => b === kind).length
    return n > 0 ? [`${n} ${n === 1 ? one : many}`] : []
  })
  const head = bars.length === 1 ? 'Última execução' : `Últimas ${bars.length} execuções`
  return `${head}: ${counts.join(', ')}`
}
