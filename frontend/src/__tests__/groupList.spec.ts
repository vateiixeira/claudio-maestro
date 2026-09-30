import { describe, expect, it } from 'vitest'
import { groupActivity, isActive, sessionsOf, sortGroups } from '../groupList'
import { makeGroup, makeSession } from '../test/factories'

describe('listas de agrupadores', () => {
  const sessions = [
    makeSession({ session_id: 'a', group_id: 1, last_activity_at: 100 }),
    makeSession({ session_id: 'b', group_id: 1, last_activity_at: 300, display_state: 'finished' }),
    makeSession({ session_id: 'c', group_id: 2, last_activity_at: 200 }),
    makeSession({ session_id: 'd', group_id: null, last_activity_at: 999 }),
  ]

  it('sessões do agrupador, da mais recente para a mais antiga', () => {
    expect(sessionsOf(1, sessions).map((s) => s.session_id)).toEqual(['b', 'a'])
  })

  it('ativa é a que não está finalizada', () => {
    expect(isActive(sessions[0]!)).toBe(true)
    expect(isActive(sessions[1]!)).toBe(false)
  })

  it('atividade do agrupador: última sessão, ou a criação quando vazio', () => {
    expect(groupActivity(makeGroup({ id: 1 }), sessions)).toBe(300)
    expect(groupActivity(makeGroup({ id: 9, created_at: 50 }), sessions)).toBe(50)
  })

  it('ordena pela atividade, mais recente primeiro', () => {
    const groups = [makeGroup({ id: 2, name: 'B' }), makeGroup({ id: 1, name: 'A' }), makeGroup({ id: 9, created_at: 400 })]
    expect(sortGroups(groups, sessions).map((g) => g.id)).toEqual([9, 1, 2])
  })
})
