import { describe, expect, it } from 'vitest'
import { OPEN_MAX, looseOpenSessions, openSessions } from '../openList'
import { makeSession } from '../../../test/factories'

const ids = (list: { session_id: string }[]) => list.map((s) => s.session_id)

describe('lista Abertas', () => {
  it('põe primeiro o que espera você, depois o que roda, depois o resto, mantendo a ordem de chegada em cada faixa', () => {
    const all = [
      makeSession({ session_id: 'quieta', display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'roda1', display_state: 'running' }),
      makeSession({ session_id: 'pede1', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'roda2', display_state: 'running' }),
      makeSession({ session_id: 'pede2', display_state: 'waiting', pending_kind: 'tool' }),
    ]
    expect(ids(openSessions(all))).toEqual(['pede1', 'pede2', 'roda1', 'roda2', 'quieta'])
  })

  it('tira as finalizadas', () => {
    const all = [
      makeSession({ session_id: 'a' }),
      makeSession({ session_id: 'fim', display_state: 'finished', finished: true }),
    ]
    expect(ids(openSessions(all))).toEqual(['a'])
  })

  it('conversa com erro conta como "espera você"', () => {
    const all = [
      makeSession({ session_id: 'roda', display_state: 'running' }),
      makeSession({ session_id: 'erro', display_state: 'waiting', state: 'error' }),
    ]
    expect(ids(openSessions(all))).toEqual(['erro', 'roda'])
  })

  it('as que esperam você entram nas primeiras 8 mesmo sendo as mais antigas', () => {
    const recentes = Array.from({ length: 10 }, (_, i) => makeSession({ session_id: `r${i}`, display_state: 'running' }))
    const antigas = [
      makeSession({ session_id: 'velha1', display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'velha2', display_state: 'waiting', unread: true }),
    ]
    const visible = openSessions([...recentes, ...antigas]).slice(0, OPEN_MAX)
    expect(ids(visible).slice(0, 2)).toEqual(['velha1', 'velha2'])
    expect(OPEN_MAX).toBe(8)
  })

  it('não altera a lista recebida', () => {
    const all = [makeSession({ session_id: 'a', display_state: 'running' }), makeSession({ session_id: 'b', display_state: 'waiting', unread: true })]
    openSessions(all)
    expect(ids(all)).toEqual(['a', 'b'])
  })
})

describe('abertas de um projeto fora dos agrupadores', () => {
  it('só do projeto, sem finalizadas, sem as de agrupador conhecido, na ordem de Abertas', () => {
    const all = [
      makeSession({ session_id: 'quieta', project_id: 1 }),
      makeSession({ session_id: 'roda', project_id: 1, display_state: 'running' }),
      makeSession({ session_id: 'outro', project_id: 2, display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'fim', project_id: 1, display_state: 'finished', finished: true }),
      makeSession({ session_id: 'agrupada', project_id: 1, group_id: 7, display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'orfa', project_id: 1, group_id: 99 }),
      makeSession({ session_id: 'pede', project_id: 1, display_state: 'waiting', unread: true }),
    ]
    expect(ids(looseOpenSessions(all, 1, new Set([7])))).toEqual(['pede', 'roda', 'quieta', 'orfa'])
  })

  it('sem agrupadores, traz todas as abertas do projeto', () => {
    const all = [makeSession({ session_id: 'a', project_id: 3, group_id: 5 }), makeSession({ session_id: 'b', project_id: 3 })]
    expect(ids(looseOpenSessions(all, 3, new Set()))).toEqual(['a', 'b'])
  })
})
