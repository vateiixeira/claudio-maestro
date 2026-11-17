import type { Run, RunOutcome } from '../types/org'

/** Outcomes of a run that has not ended yet. */
export const IN_FLIGHT: ReadonlySet<RunOutcome> = new Set<RunOutcome>(['starting', 'running', 'waiting'])

export type TimelineRow =
  | { kind: 'turn'; key: string; index: number } // position in the turns array received
  | { kind: 'run'; key: string; run: Run }

const runTime = (run: Run): number => run.ended_at ?? run.started_at

/**
 * Interleaves the turns of an agent's main conversation with its runs, so the screen draws
 * everything in one timeline. `turnTimes[i]` is the `at` (Unix seconds) of the message that opens
 * turn i, or null. Turns never change order; finished runs slot in by time (a tie goes after the
 * turn); runs in flight go to the end; runs of the main session are left out (they are the turns).
 */
export function buildAgentTimeline(
  turnTimes: (number | null)[],
  runs: Run[],
  mainSessionId: string,
): TimelineRow[] {
  // A turn without a time inherits the one before it; leading ones come before everything.
  let last = -Infinity
  const effective = turnTimes.map((t) => {
    if (t !== null) last = t
    return last
  })

  const candidates = runs.filter((r) => r.session_id !== mainSessionId)
  const live = candidates
    .filter((r) => IN_FLIGHT.has(r.outcome))
    .sort((a, b) => a.started_at - b.started_at || a.id - b.id)
  const finished = candidates
    .filter((r) => !IN_FLIGHT.has(r.outcome))
    .sort((a, b) => runTime(a) - runTime(b) || a.id - b.id)

  // slots[i] holds the runs that come right before turn i; slots[n] the ones after the last turn.
  const slots: Run[][] = Array.from({ length: turnTimes.length + 1 }, () => [])
  for (const r of finished) {
    const at = runTime(r)
    const i = effective.findIndex((t) => t > at)
    slots[i === -1 ? turnTimes.length : i].push(r)
  }

  const rows: TimelineRow[] = []
  const pushRun = (run: Run) => rows.push({ kind: 'run', key: `run-${run.id}`, run })
  for (let i = 0; i < turnTimes.length; i++) {
    slots[i].forEach(pushRun)
    rows.push({ kind: 'turn', key: `turn-${i}`, index: i })
  }
  slots[turnTimes.length].forEach(pushRun)
  live.forEach(pushRun)
  return rows
}
