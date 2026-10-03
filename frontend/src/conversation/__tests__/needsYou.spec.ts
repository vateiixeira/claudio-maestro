import { describe, expect, it } from 'vitest'
import { needsYou } from '../needsYou'
import { isQuietSession } from '../../components/sidebar/itemClass'
import { makeSession } from '../../test/factories'

describe('needsYou', () => {
  it('is false for a plain wait with nothing new', () => {
    expect(needsYou(makeSession({ display_state: 'waiting', unread: false, state: 'idle' }))).toBe(false)
  })

  it('is true for unread, a pending decision or an error', () => {
    expect(needsYou(makeSession({ unread: true }))).toBe(true)
    for (const kind of ['tool', 'question', 'plan'] as const) {
      expect(needsYou(makeSession({ pending_kind: kind }))).toBe(true)
    }
    expect(needsYou(makeSession({ state: 'error' }))).toBe(true)
  })

  it('a sessão bloqueada numa decisão pede você mesmo antes de pending_kind chegar', () => {
    expect(needsYou(makeSession({ state: 'awaiting_decision', pending_kind: null, unread: false }))).toBe(true)
  })

  it('uma sessão marcada só pede você com pedido real, não por estar não lida', () => {
    expect(needsYou(makeSession({ unread: true, mark: 'on_hold' }))).toBe(false)
    expect(needsYou(makeSession({ unread: true, mark: 'blocked' }))).toBe(false)
    expect(needsYou(makeSession({ unread: true, mark: 'review' }))).toBe(false)
    expect(needsYou(makeSession({ unread: true, mark: null }))).toBe(true)
    expect(needsYou(makeSession({ unread: true }))).toBe(true)
    expect(needsYou(makeSession({ unread: false, mark: 'on_hold', pending_kind: 'tool' }))).toBe(true)
    expect(needsYou(makeSession({ unread: false, mark: 'blocked', state: 'error' }))).toBe(true)
    expect(needsYou(makeSession({ unread: false, mark: 'review', state: 'awaiting_decision' }))).toBe(true)
  })

  it('isQuietSession is its negation', () => {
    for (const s of [makeSession(), makeSession({ unread: true }), makeSession({ state: 'error' }), makeSession({ pending_kind: 'plan' }), makeSession({ unread: true, mark: 'on_hold' })]) {
      expect(isQuietSession(s)).toBe(!needsYou(s))
    }
  })
})
