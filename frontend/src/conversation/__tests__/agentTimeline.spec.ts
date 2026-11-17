import { describe, expect, it } from 'vitest'
import { buildAgentTimeline, type TimelineRow } from '../agentTimeline'
import type { Run } from '../../types/org'

const run = (id: number, over: Partial<Run> = {}): Run => ({
  id, agent_id: 1, session_id: `s${id}`, source: 'routine', routine_id: null, scheduled_for: null,
  started_at: 100, ended_at: 110, outcome: 'concluded', reason: null, task_id: null,
  commented: false, rewoken: false, summary: null, ...over,
})
const keys = (rows: TimelineRow[]) => rows.map((r) => r.key)

describe('buildAgentTimeline', () => {
  it('puts a finished run between the turns around its end', () => {
    expect(keys(buildAgentTimeline([50, 200], [run(1, { ended_at: 110 })], 'main'))).toEqual(['turn-0', 'run-1', 'turn-1'])
  })
  it('keeps runs older than the first loaded turn at the top, in order', () => {
    expect(keys(buildAgentTimeline([500], [run(2, { ended_at: 90 }), run(1, { ended_at: 80 })], 'main'))).toEqual(['run-1', 'run-2', 'turn-0'])
  })
  it('sends runs in flight to the end', () => {
    const live = run(3, { outcome: 'running', ended_at: null, started_at: 10 })
    expect(keys(buildAgentTimeline([50, 200], [live, run(1)], 'main'))).toEqual(['turn-0', 'run-1', 'turn-1', 'run-3'])
  })
  it('leaves out the runs of the main session', () => {
    expect(keys(buildAgentTimeline([50], [run(1, { session_id: 'main' })], 'main'))).toEqual(['turn-0'])
  })
  it('keeps a turn without a time after the one before it', () => {
    expect(keys(buildAgentTimeline([50, null, 300], [run(1, { ended_at: 110 })], 'main'))).toEqual(['turn-0', 'turn-1', 'run-1', 'turn-2'])
  })
  it('uses the start of a run that has no end and is not in flight', () => {
    expect(keys(buildAgentTimeline([50, 200], [run(1, { outcome: 'missed', session_id: null, ended_at: null, started_at: 120 })], 'main'))).toEqual(['turn-0', 'run-1', 'turn-1'])
  })
  it('puts a run that ended at the very time of a turn after that turn', () => {
    expect(keys(buildAgentTimeline([110], [run(1, { ended_at: 110 })], 'main'))).toEqual(['turn-0', 'run-1'])
  })
  it('keeps leading turns without a time before everything', () => {
    expect(keys(buildAgentTimeline([null, 200], [run(1, { ended_at: 110 })], 'main'))).toEqual(['turn-0', 'run-1', 'turn-1'])
  })
  it('orders runs in flight by start and ties by id', () => {
    const a = run(5, { outcome: 'running', ended_at: null, started_at: 30 })
    const b = run(4, { outcome: 'waiting', ended_at: null, started_at: 20 })
    const c = run(2, { outcome: 'starting', ended_at: null, started_at: 20 })
    expect(keys(buildAgentTimeline([50], [a, b, c], 'main'))).toEqual(['turn-0', 'run-2', 'run-4', 'run-5'])
  })
})
