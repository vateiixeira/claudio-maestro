import { describe, expect, it } from 'vitest'
import { groupActivity, groupOptionLabel, isActive, removeGroupText, selectorGroups, sessionsOf, sortGroups, visibleGroups } from '../groupList'
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

describe('agrupadores entre projetos', () => {
  const groups = [
    makeGroup({ id: 1, project_id: 1, name: 'Origem vazia', created_at: 10 }),
    makeGroup({ id: 2, project_id: 2, name: 'Pagamento', created_at: 20 }),
    makeGroup({ id: 3, project_id: 2, name: 'So descartada', created_at: 30 }),
    makeGroup({ id: 4, project_id: 2, name: 'Alheio', created_at: 40 }),
  ]
  const sessions = [
    makeSession({ session_id: 'a', project_id: 1, group_id: 2, last_activity_at: 50 }),
    makeSession({ session_id: 'b', project_id: 2, group_id: 2, last_activity_at: 60 }),
    makeSession({ session_id: 'c', project_id: 1, group_id: 3, mark: 'discarded', last_activity_at: 5 }),
  ]

  it('visível no projeto: o criado nele (mesmo vazio) e o que tem conversa dele', () => {
    expect(visibleGroups(groups, sessions, 1).map((g) => g.id)).toEqual([1, 2])
    expect(visibleGroups(groups, sessions, 2).map((g) => g.id)).toEqual([2, 3, 4])
  })

  it('conversa descartada não faz o agrupador aparecer no projeto dela', () => {
    expect(visibleGroups(groups, sessions, 1).map((g) => g.id)).not.toContain(3)
  })

  it('seletor: os visíveis primeiro, depois o resto, cada bloco pela atividade', () => {
    expect(selectorGroups(groups, sessions, 1).map((g) => g.id)).toEqual([2, 1, 4, 3])
  })

  it('rótulo do seletor: nome puro no projeto de origem, "Nome · Projeto" fora dele', () => {
    const projects = [{ id: 1, name: 'api' }, { id: 2, name: 'web' }]
    expect(groupOptionLabel(groups[1]!, 2, projects)).toBe('Pagamento')
    expect(groupOptionLabel(groups[1]!, 1, projects)).toBe('Pagamento · web')
    expect(groupOptionLabel(groups[1]!, 1, [])).toBe('Pagamento')
  })

  it('texto da remoção: vazio, uma, várias e de vários projetos', () => {
    expect(removeGroupText([])).toBe('O agrupador está vazio.')
    expect(removeGroupText([makeSession({ session_id: 'a' })])).toBe('A conversa volta a ficar solta; nenhuma é apagada.')
    const two = [makeSession({ session_id: 'a' }), makeSession({ session_id: 'b' })]
    expect(removeGroupText(two)).toBe('As 2 conversas voltam a ficar soltas; nenhuma é apagada.')
    const mixed = [makeSession({ session_id: 'a', project_id: 1 }), makeSession({ session_id: 'b', project_id: 2 })]
    expect(removeGroupText(mixed)).toBe('As 2 conversas, de 2 projetos, voltam a ficar soltas; nenhuma é apagada.')
  })
})
