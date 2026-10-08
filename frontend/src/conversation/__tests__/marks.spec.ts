import { describe, expect, it } from 'vitest'
import { markChipText, markLane, nextMondayAt9, tomorrowAt9, untilShort } from '../marks'
import { makeSession } from '../../test/factories'

const at = (y: number, m: number, d: number, h = 14, min = 0) => new Date(y, m - 1, d, h, min)
const secs = (date: Date) => Math.floor(date.getTime() / 1000)

describe('markLane', () => {
  it('sem marcação fica em agora', () => {
    expect(markLane(makeSession())).toBe('now')
  })
  it('para revisar vai para revisar; em espera e bloqueada vão para depois', () => {
    expect(markLane(makeSession({ mark: 'review' }))).toBe('review')
    expect(markLane(makeSession({ mark: 'on_hold' }))).toBe('later')
    expect(markLane(makeSession({ mark: 'blocked' }))).toBe('later')
  })
  it('pedido do Claude vence a marcação (Review Focus 1)', () => {
    expect(markLane(makeSession({ mark: 'on_hold', pending_kind: 'tool' }))).toBe('now')
    expect(markLane(makeSession({ mark: 'blocked', state: 'awaiting_decision' }))).toBe('now')
    expect(markLane(makeSession({ mark: 'review', state: 'error' }))).toBe('now')
  })
  it('novidade não lida não é pedido', () => {
    expect(markLane(makeSession({ mark: 'on_hold', unread: true }))).toBe('later')
  })
})

describe('datas de espera', () => {
  it('amanhã às 9h', () => {
    expect(tomorrowAt9(at(2026, 10, 3))).toBe(secs(at(2026, 10, 4, 9)))
  })
  it('próxima segunda às 9h a partir de um sábado', () => {
    expect(nextMondayAt9(at(2026, 10, 3))).toBe(secs(at(2026, 10, 5, 9)))
  })
  it('numa segunda, vai para a segunda seguinte (Review Focus 5)', () => {
    expect(nextMondayAt9(at(2026, 10, 5, 8))).toBe(secs(at(2026, 10, 12, 9)))
  })
  it('num domingo, vai para o dia seguinte', () => {
    expect(nextMondayAt9(at(2026, 10, 4))).toBe(secs(at(2026, 10, 5, 9)))
  })
  it('rótulo curto: hoje, amanhã, dia da semana até 6 dias, depois dd/mm', () => {
    const now = at(2026, 10, 3)
    expect(untilShort(secs(at(2026, 10, 3, 20)), now)).toBe('hoje')
    expect(untilShort(secs(at(2026, 10, 4, 9)), now)).toBe('amanhã')
    expect(untilShort(secs(at(2026, 10, 5, 9)), now)).toBe('seg')
    expect(untilShort(secs(at(2026, 10, 12, 9)), now)).toBe('12/10')
  })
})

describe('markChipText', () => {
  const now = at(2026, 10, 3)
  it('em espera com e sem data', () => {
    expect(markChipText({ mark: 'on_hold', mark_until: secs(at(2026, 10, 5, 9)) }, now)).toBe('Em espera até seg 09:00')
    expect(markChipText({ mark: 'on_hold' }, now)).toBe('Em espera')
  })
  it('bloqueada com nota', () => {
    expect(markChipText({ mark: 'blocked', mark_note: 'esperando CI' }, now)).toBe('Bloqueada: esperando CI')
  })
  it('sem marcação devolve null', () => {
    expect(markChipText({ mark: null }, now)).toBeNull()
  })
})

describe('sessões descartadas', () => {
  it('ficam numa faixa própria, mesmo com pedido do Claude ou rodando', () => {
    expect(markLane(makeSession({ mark: 'discarded' }))).toBe('discarded')
    expect(markLane(makeSession({ mark: 'discarded', pending_kind: 'tool' }))).toBe('discarded')
    expect(markLane(makeSession({ mark: 'discarded', display_state: 'running' }))).toBe('discarded')
  })
  it('o chip da conversa diz Descartada', () => {
    expect(markChipText({ mark: 'discarded' }, new Date())).toBe('Descartada')
  })
})
