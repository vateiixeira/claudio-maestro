import { describe, expect, it } from 'vitest'
import { projectTree } from '../sidebarTree'
import { makeGroup, makeSession } from '../test/factories'

describe('árvore do menu', () => {
  it('separa agrupadores com sessão ativa dos parados e só lista as ativas', () => {
    const groups = [makeGroup({ id: 1, name: 'A' }), makeGroup({ id: 2, name: 'B' }), makeGroup({ id: 3, name: 'Vazio' })]
    const sessions = [
      makeSession({ session_id: 'a1', group_id: 1, last_activity_at: 10, display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'a2', group_id: 1, last_activity_at: 20, display_state: 'finished' }),
      makeSession({ session_id: 'a3', group_id: 1, last_activity_at: 30, display_state: 'running' }),
      makeSession({ session_id: 'b1', group_id: 2, display_state: 'finished' }),
    ]
    const tree = projectTree(groups, sessions)
    expect(tree.active.map((g) => g.group.id)).toEqual([1])
    expect(tree.active[0]!.sessions.map((s) => s.session_id)).toEqual(['a3', 'a1'])
    expect(tree.active[0]!.waiting).toBe(1)
    expect(tree.idle.map((g) => g.id).sort()).toEqual([2, 3])
  })

  it('conta como aguardando só quem precisa de você', () => {
    const sessions = [
      makeSession({ session_id: 'q', group_id: 1, display_state: 'waiting', unread: false }),
      makeSession({ session_id: 'u', group_id: 1, display_state: 'waiting', unread: true }),
      makeSession({ session_id: 'p', group_id: 1, display_state: 'waiting', pending_kind: 'plan' }),
      makeSession({ session_id: 'e', group_id: 1, display_state: 'waiting', state: 'error' }),
    ]
    expect(projectTree([makeGroup({ id: 1 })], sessions).active[0]!.waiting).toBe(3)
  })

  it('não conta como aguardando a sessão marcada sem pedido real', () => {
    const sessions = [
      makeSession({ session_id: 'm', group_id: 1, display_state: 'waiting', unread: true, mark: 'on_hold' }),
      makeSession({ session_id: 'r', group_id: 1, display_state: 'waiting', unread: true, mark: 'blocked', pending_kind: 'tool' }),
    ]
    expect(projectTree([makeGroup({ id: 1 })], sessions).active[0]!.waiting).toBe(1)
  })
})
