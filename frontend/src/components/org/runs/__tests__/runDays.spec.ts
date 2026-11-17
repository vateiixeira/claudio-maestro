import { describe, expect, it } from 'vitest'
import {
  PROBLEM_OUTCOMES, dayLabel, durationShare, groupByDay, offAgentsText, runLines, runsSummary, slowFactor, slowText,
} from '../runDays'
import { makeRun } from '../../../../test/factories'
import type { Run, RunOutcome } from '../../../../types/org'

const now = new Date(2026, 10, 17, 10, 40) // terça, 17 nov 2026
/** Segundos locais de uma data de nov/2026. */
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime() / 1000
const atDate = (y: number, mo: number, d: number, h = 9, m = 0) => new Date(y, mo, d, h, m).getTime() / 1000

function mk(id: number, outcome: RunOutcome, started: number, extra: Partial<Run> = {}): Run {
  return makeRun({ id, outcome, started_at: started, ended_at: started + 60, ...extra })
}
const missed = (id: number, started: number) => mk(id, 'missed', started)
const concluded = (id: number, started: number, extra: Partial<Run> = {}) => mk(id, 'concluded', started, extra)
const failed = (id: number, started: number) => mk(id, 'failed', started)

describe('PROBLEM_OUTCOMES', () => {
  it('guarda os resultados que pedem atenção', () => {
    expect([...PROBLEM_OUTCOMES].sort()).toEqual(['failed', 'missed', 'skipped', 'waiting'])
  })
})

describe('dayLabel', () => {
  it('Hoje, Ontem e a data com o dia da semana', () => {
    expect(dayLabel(at(17, 8, 0), now)).toBe('Hoje')
    expect(dayLabel(at(16, 18, 40), now)).toBe('Ontem')
    expect(dayLabel(at(13, 18, 40), now)).toBe('13 nov · sexta')
    expect(dayLabel(atDate(2025, 10, 13), now)).toBe('13 nov 2025 · quinta')
  })

  it('ontem vale na virada do mês', () => {
    expect(dayLabel(atDate(2026, 9, 31, 23, 50), new Date(2026, 10, 1, 8))).toBe('Ontem')
  })
})

describe('runLines', () => {
  it('junta as perdidas do mesmo minuto numa linha e deixa a concluída sozinha', () => {
    const lines = runLines([missed(1, at(10, 9, 4)), missed(2, at(10, 9, 4) + 20), concluded(3, at(10, 7, 40))])
    expect(lines.map((l) => l.kind)).toEqual(['missed', 'run'])
    const first = lines[0]!
    expect(first.kind === 'missed' && first.runs.map((r) => r.id)).toEqual([1, 2])
  })

  it('perdidas de minutos diferentes ficam separadas', () => {
    expect(runLines([missed(1, at(10, 9, 5)), missed(2, at(10, 9, 4))]).map((l) => l.kind)).toEqual(['missed', 'missed'])
  })

  it('uma perdida sozinha continua sendo uma linha de perdida', () => {
    const [line] = runLines([missed(1, at(10, 9, 4))])
    expect(line).toEqual({ kind: 'missed', runs: [missed(1, at(10, 9, 4))] })
  })
})

describe('groupByDay', () => {
  it('agrupa por dia local, da mais nova para a mais antiga', () => {
    const runs = [concluded(3, at(17, 9, 0)), concluded(2, at(13, 18, 40)), missed(1, at(13, 9, 0))]
    const groups = groupByDay(runLines(runs), now)
    expect(groups.map((g) => g.label)).toEqual(['Hoje', '13 nov · sexta'])
    expect(groups.map((g) => g.key)).toEqual(['2026-11-17', '2026-11-13'])
    expect(groups[1]!.lines).toHaveLength(2)
  })
})

describe('runsSummary', () => {
  it('conta por resultado e explica as perdidas', () => {
    const eight = [9, 9, 10, 11, 11, 12, 13, 13].map((d, i) => concluded(i + 1, at(d, 9, i)))
    const four = [9, 10, 12, 13].map((d, i) => missed(i + 20, at(d, 12, 0)))
    expect(runsSummary([...eight, ...four])).toBe('De 9 a 13 nov: 8 concluídas, 4 perdidas (o horário passou sem o Maestro disparar o agente).')
  })

  it('um dia só, e entre meses', () => {
    expect(runsSummary([concluded(1, at(13, 18, 40))])).toBe('Em 13 nov: 1 concluída.')
    expect(runsSummary([concluded(1, atDate(2026, 9, 28)), concluded(2, atDate(2026, 10, 3))])).toBe('De 28 out a 3 nov: 2 concluídas.')
    expect(runsSummary([failed(1, at(13, 9, 0))])).toBe('Em 13 nov: 1 com falha.')
  })

  it('execuções em andamento e lista vazia não resumem', () => {
    expect(runsSummary([])).toBeNull()
    expect(runsSummary([makeRun({ outcome: 'running' })])).toBeNull()
  })
})

describe('offAgentsText', () => {
  it('concorda no singular e no plural', () => {
    expect(offAgentsText([])).toBeNull()
    expect(offAgentsText(['Triagem'])).toBe('Triagem está desligado: nada dele roda até você ligar.')
    expect(offAgentsText(['Revisor', 'Triagem'])).toBe('Revisor e Triagem estão desligados: nada deles roda até você ligar.')
    expect(offAgentsText(['A', 'B', 'C'])).toBe('A, B e C estão desligados: nada deles roda até você ligar.')
  })
})

describe('slowFactor', () => {
  const base = 1_790_000_000
  const timed = (id: number, seconds: number, extra: Partial<Run> = {}) =>
    makeRun({ id, outcome: 'concluded', started_at: base + id * 1000, ended_at: base + id * 1000 + seconds, routine_id: 7, ...extra })
  const four = [1, 2, 3, 4].map((i) => timed(i, 60))

  it('compara com a mediana da mesma rotina', () => {
    const slow = timed(10, 1500)
    expect(slowFactor(slow, [slow, ...four])).toEqual({ factor: 25, scope: 'routine' })
  })

  it('não destaca abaixo de 3 vezes', () => {
    const run = timed(10, 150)
    expect(slowFactor(run, [run, ...four])).toBeNull()
  })

  it('precisa de quatro outras para comparar', () => {
    const slow = timed(10, 1500)
    expect(slowFactor(slow, [slow, ...four.slice(0, 3)])).toBeNull()
  })

  it('execução sem fim não é comparada', () => {
    const running = makeRun({ id: 10, outcome: 'running', started_at: base, ended_at: null, routine_id: 7 })
    expect(slowFactor(running, [running, ...four])).toBeNull()
  })

  it('sem rotina compara só com as do mesmo agente que também não têm rotina', () => {
    const noRoutine = [1, 2, 3, 4].map((i) => timed(i, 60, { routine_id: null }))
    const slow = timed(10, 240, { routine_id: null })
    expect(slowFactor(slow, [slow, ...noRoutine])).toEqual({ factor: 4, scope: 'agent' })
    // com rotina e de outro agente, não contam
    const others = [1, 2, 3, 4].map((i) => timed(i, 60, { routine_id: 7 }))
    expect(slowFactor(slow, [slow, ...others])).toBeNull()
    const otherAgent = [1, 2, 3, 4].map((i) => timed(i, 60, { routine_id: null, agent_id: 2 }))
    expect(slowFactor(slow, [slow, ...otherAgent])).toBeNull()
  })

  it('mediana zero não compara', () => {
    const zero = [1, 2, 3, 4].map((i) => timed(i, 0))
    const slow = timed(10, 100)
    expect(slowFactor(slow, [slow, ...zero])).toBeNull()
  })

  it('só as concluídas entram na mediana', () => {
    const slow = timed(10, 1500)
    const noise = [1, 2, 3, 4].map((i) => timed(i, 60, { outcome: 'failed' }))
    expect(slowFactor(slow, [slow, ...noise])).toBeNull()
  })
})

describe('slowText', () => {
  it('diz a rotina ou o agente', () => {
    expect(slowText({ factor: 25, scope: 'routine' })).toBe('Levou 25 vezes mais que o normal desta rotina')
    expect(slowText({ factor: 4, scope: 'agent' })).toBe('Levou 4 vezes mais que o normal deste agente')
  })
})

describe('durationShare', () => {
  it('é a parte da maior duração, em porcentagem', () => {
    expect(durationShare(makeRun({ started_at: 100, ended_at: 160 }), 600)).toBe(10)
    expect(durationShare(makeRun({ started_at: 100, ended_at: 700 }), 600)).toBe(100)
    expect(durationShare(makeRun({ started_at: 100, ended_at: null }), 600)).toBe(0)
    expect(durationShare(makeRun({ started_at: 100, ended_at: 160 }), 0)).toBe(0)
  })
})
