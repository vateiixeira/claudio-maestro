import { describe, expect, it } from 'vitest'
import { projectTree, splitProjects } from '../sidebarTree'
import { makeGroup, makeProject, makeSession } from '../test/factories'

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

describe('projetos do menu: em andamento e outros', () => {
  const projects = [makeProject({ id: 1, name: 'a' }), makeProject({ id: 2, name: 'b' }), makeProject({ id: 3, name: 'c' })]

  it('põe em andamento o projeto com conversa aberta e mantém a ordem dos projetos', () => {
    const sessions = [makeSession({ session_id: 's3', project_id: 3 }), makeSession({ session_id: 's1', project_id: 1, display_state: 'running' })]
    const split = splitProjects(projects, sessions)
    expect(split.active.map((p) => p.id)).toEqual([1, 3])
    expect(split.others.map((p) => p.id)).toEqual([2])
  })

  it('conversa finalizada não conta como aberta', () => {
    const sessions = [makeSession({ session_id: 'f', project_id: 1, display_state: 'finished', finished: true })]
    const split = splitProjects(projects, sessions)
    expect(split.active).toEqual([])
    expect(split.others.map((p) => p.id)).toEqual([1, 2, 3])
  })

  it('o projeto sobe para em andamento quando ganha conversa e desce quando ela termina', () => {
    const before = splitProjects(projects, [])
    expect(before.active).toEqual([])
    const open = makeSession({ session_id: 'n', project_id: 2 })
    expect(splitProjects(projects, [open]).active.map((p) => p.id)).toEqual([2])
    const done = makeSession({ session_id: 'n', project_id: 2, display_state: 'finished', finished: true })
    expect(splitProjects(projects, [done]).active).toEqual([])
  })

  it('conversa marcada ou de agrupador também mantém o projeto em andamento', () => {
    const sessions = [makeSession({ session_id: 'm', project_id: 1, mark: 'on_hold' }), makeSession({ session_id: 'g', project_id: 2, group_id: 9 })]
    expect(splitProjects(projects, sessions).active.map((p) => p.id)).toEqual([1, 2])
  })
})
