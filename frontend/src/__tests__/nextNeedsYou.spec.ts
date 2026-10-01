import { describe, expect, it } from 'vitest'
import { needsYouQueue, nextNeedsYou } from '../nextNeedsYou'
import { makeSession } from '../test/factories'

describe('fila de conversas que aguardam você', () => {
  it('só entra espera que precisa de você, na ordem da aba da Inbox', () => {
    const all = [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: true, last_activity_at: 30 }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: false, last_activity_at: 25 }),
      makeSession({ session_id: 'c', display_state: 'running', unread: true, last_activity_at: 20 }),
      makeSession({ session_id: 'd', display_state: 'waiting', pending_kind: 'tool', last_activity_at: 10 }),
      makeSession({ session_id: 'e', display_state: 'finished', unread: true, last_activity_at: 5 }),
      makeSession({ session_id: 'f', display_state: 'waiting', state: 'error', last_activity_at: 1 }),
    ]
    expect(needsYouQueue(all, null).map((s) => s.session_id)).toEqual(['a', 'd', 'f'])
  })

  it('exclui a conversa atual', () => {
    const all = [
      makeSession({ session_id: 'a', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'b', display_state: 'waiting', unread: true }),
    ]
    expect(needsYouQueue(all, 'a').map((s) => s.session_id)).toEqual(['b'])
    expect(needsYouQueue(all, 'b').map((s) => s.session_id)).toEqual(['a'])
    expect(needsYouQueue(all, 'zzz')).toHaveLength(2)
  })

  it('fica vazia sem nenhuma outra', () => {
    const all = [makeSession({ session_id: 'a', display_state: 'waiting', unread: true })]
    expect(needsYouQueue(all, 'a')).toEqual([])
    expect(needsYouQueue([], undefined)).toEqual([])
  })
})

describe('próxima conversa que aguarda você', () => {
  const waiting = (id: string, at: number) => makeSession({ session_id: id, display_state: 'waiting', unread: true, last_activity_at: at })

  it('percorre a fila em ordem e volta ao início: A→B, B→C, C→A', () => {
    const all = [waiting('a', 30), waiting('b', 20), waiting('c', 10)]
    expect(nextNeedsYou(all, 'a')?.session_id).toBe('b')
    expect(nextNeedsYou(all, 'b')?.session_id).toBe('c')
    expect(nextNeedsYou(all, 'c')?.session_id).toBe('a')
  })

  it('se a atual não está na fila, vai à primeira', () => {
    const all = [waiting('a', 30), waiting('b', 20), makeSession({ session_id: 'x', display_state: 'running' })]
    expect(nextNeedsYou([makeSession({ session_id: 'x', display_state: 'running' }), ...all.slice(0, 2)], 'x')?.session_id).toBe('a')
    expect(nextNeedsYou(all, 'x')?.session_id).toBe('a')
    expect(nextNeedsYou(all, null)?.session_id).toBe('a')
  })

  it('segue a ordem da lista mesmo se a atual está no meio de outras da fila', () => {
    const all = [waiting('a', 30), makeSession({ session_id: 'x', display_state: 'running' }), waiting('b', 20), waiting('c', 10)]
    expect(nextNeedsYou(all, 'b')?.session_id).toBe('c')
  })

  it('devolve nada sem outra conversa aguardando você', () => {
    expect(nextNeedsYou([waiting('a', 1)], 'a')).toBeNull()
    expect(nextNeedsYou([], 'a')).toBeNull()
  })
})
