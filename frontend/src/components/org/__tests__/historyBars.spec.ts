import { describe, expect, it } from 'vitest'
import { historyBars, historyLabel } from '../runHistory'
import { makeRun } from '../../../test/factories'
import type { RunOutcome } from '../../../types/org'

let nextId = 1
const run = (outcome: RunOutcome) => makeRun({ id: nextId++, outcome })

describe('historyBars', () => {
  it('ignora as execuções em andamento e devolve da mais antiga para a mais nova', () => {
    const newestFirst = [run('missed'), run('concluded'), run('running'), run('failed'), run('closed')]
    expect(historyBars(newestFirst)).toEqual(['ok', 'fail', 'ok', 'miss'])
  })

  it('ignora starting', () => {
    expect(historyBars([run('starting'), run('concluded')])).toEqual(['ok'])
  })

  it('mapeia cada resultado', () => {
    expect(historyBars([run('waiting'), run('skipped'), run('cancelled'), run('missed')])).toEqual(['miss', 'miss', 'miss', 'wait'])
  })

  it('guarda no máximo 14, as mais novas', () => {
    const many = Array.from({ length: 20 }, () => run('concluded'))
    expect(historyBars(many)).toHaveLength(14)
    const mixed = [...Array.from({ length: 14 }, () => run('failed')), run('concluded')]
    expect(historyBars(mixed)).toEqual(Array(14).fill('fail'))
    expect(historyBars([run('concluded'), run('failed'), run('failed')], 2)).toEqual(['fail', 'ok'])
  })

  it('lista vazia não tem barras', () => {
    expect(historyBars([])).toEqual([])
  })
})

describe('historyLabel', () => {
  it('conta cada tipo', () => {
    expect(historyLabel(['ok', 'fail', 'ok', 'miss'])).toBe('Últimas 4 execuções: 2 concluídas, 1 com falha, 1 perdida')
    expect(historyLabel(['wait', 'miss', 'miss'])).toBe('Últimas 3 execuções: 1 esperando você, 2 perdidas')
  })

  it('usa o singular com uma só', () => {
    expect(historyLabel(['ok'])).toBe('Última execução: 1 concluída')
  })
})

describe('historyBars com execuções perdidas', () => {
  it('ordena pela hora agendada, não pela da detecção', () => {
    const detected = 1_790_100_000
    const sent = [
      makeRun({ id: 2, outcome: 'missed', scheduled_for: 1_790_000_000, started_at: detected }),
      makeRun({ id: 1, outcome: 'concluded', started_at: 1_790_050_000 }),
    ]
    // vinda da loja (por started_at, a perdida primeiro), a mais antiga pela hora agendada é a perdida
    expect(historyBars(sent)).toEqual(['miss', 'ok'])
  })
})
