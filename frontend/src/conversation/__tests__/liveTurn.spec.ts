import { describe, expect, it } from 'vitest'
import { buildTurns } from '../turns'
import { liveActivity, showTurnTasks, tokensLabel, turnTaskStates } from '../liveTurn'
import type { ConversationItem, ToolItem } from '../../types/conversation'

const user = (id: string): ConversationItem => ({ type: 'user', id, text: id })
const text = (id: string, streaming = false): ConversationItem => ({ type: 'text', id, text: id, streaming, parent_tool_use_id: null })
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra }
}
const todos = (id: string, ...items: [string, string][]) =>
  tool(id, 'TodoWrite', { todos: items.map(([content, status]) => ({ content, status })) })
const running = (id: string, name: string, input: Record<string, unknown>) => tool(id, name, input, { result: null })

describe('turnTaskStates', () => {
  it('guarda a lista ao fim de cada turno e se o turno mexeu nela', () => {
    const turns = buildTurns([
      user('u1'), todos('t1', ['a', 'in_progress'], ['b', 'pending']),
      user('u2'), text('x'),
      user('u3'), todos('t2', ['a', 'completed'], ['b', 'completed']),
    ])
    const states = turnTaskStates(turns)
    expect(states.map((s) => s.touched)).toEqual([true, false, true])
    expect(states[0]!.tasks.map((t) => t.status)).toEqual(['in_progress', 'pending'])
    // A conversa sem relação herda a lista, mas não mexeu nela.
    expect(states[1]!.tasks.map((t) => t.status)).toEqual(['in_progress', 'pending'])
    expect(states[2]!.tasks.map((t) => t.status)).toEqual(['completed', 'completed'])
  })

  it('segue TaskCreate e TaskUpdate de um turno para o outro', () => {
    const turns = buildTurns([
      user('u1'), tool('c1', 'TaskCreate', { subject: 'Escrever teste' }, { result: { content: 'Task #1 created successfully', is_error: false, details: null } }),
      user('u2'), tool('up', 'TaskUpdate', { taskId: '1', status: 'completed' }),
    ])
    const states = turnTaskStates(turns)
    expect(states[0]!.tasks).toEqual([{ id: '1', subject: 'Escrever teste', status: 'pending' }])
    expect(states[1]!.tasks).toEqual([{ id: '1', subject: 'Escrever teste', status: 'completed' }])
    expect(states[1]!.touched).toBe(true)
  })

  it('sem nenhuma ferramenta de tarefa a lista é vazia', () => {
    const [state] = turnTaskStates(buildTurns([user('u1'), text('x')]))
    expect(state).toEqual({ tasks: [], touched: false })
  })
})

describe('showTurnTasks', () => {
  const state = (statuses: string[], touched: boolean) => ({
    tasks: statuses.map((status, i) => ({ id: String(i), subject: `t${i}`, status: status as 'pending' })),
    touched,
  })

  it('turno terminado: só se alguma ferramenta de tarefa foi chamada nele', () => {
    expect(showTurnTasks(state(['pending'], true), true)).toBe(true)
    expect(showTurnTasks(state(['pending'], false), true)).toBe(false)
  })

  it('turno em andamento: lista vigente com tarefa não concluída, mesmo vinda de turno anterior', () => {
    expect(showTurnTasks(state(['completed', 'in_progress'], false), false)).toBe(true)
  })

  it('turno em andamento: tudo concluído e o turno não mexeu, não mostra', () => {
    expect(showTurnTasks(state(['completed', 'completed'], false), false)).toBe(false)
  })

  it('turno em andamento: tudo concluído mas o turno mexeu, mostra', () => {
    expect(showTurnTasks(state(['completed', 'completed'], true), false)).toBe(true)
  })

  it('sem tarefas nunca mostra', () => {
    expect(showTurnTasks(state([], true), true)).toBe(false)
    expect(showTurnTasks(state([], true), false)).toBe(false)
  })
})

describe('liveActivity', () => {
  const lastTurn = (...items: ConversationItem[]) => buildTurns([user('u'), ...items]).at(-1)!
  const none = new Set<string>()

  it('"Pensando" quando nada roda nem escreve', () => {
    expect(liveActivity(lastTurn(), true, none, false)).toBe('Pensando')
    expect(liveActivity(lastTurn(text('a')), true, none, false)).toBe('Pensando')
  })

  it('"Escrevendo" com texto em streaming', () => {
    expect(liveActivity(lastTurn(text('a', true)), true, none, false)).toBe('Escrevendo')
  })

  it('a ação em execução, no texto do bloco recolhido', () => {
    const turn = lastTurn(running('b', 'Bash', { command: 'pnpm test', description: 'Rodar os testes' }))
    expect(liveActivity(turn, true, none, false)).toBe('Comando · Rodar os testes')
  })

  it('a ação em execução vence o texto em streaming', () => {
    const turn = lastTurn(running('r', 'Read', { file_path: '/p/a.py' }), text('a', true))
    expect(liveActivity(turn, true, none, false)).toBe('Leitura · /p/a.py')
  })

  it('ação já concluída não conta', () => {
    expect(liveActivity(lastTurn(tool('r', 'Read', { file_path: '/p/a.py' })), true, none, false)).toBe('Pensando')
  })

  it('"esperando você" vence tudo quando há pedido pendente', () => {
    const turn = lastTurn(running('b', 'Bash', { command: 'ls' }), text('a', true))
    expect(liveActivity(turn, true, new Set(['tu-b']), true)).toBe('esperando você')
    expect(liveActivity(lastTurn(), true, none, true)).toBe('esperando você')
  })
})

describe('tokensLabel', () => {
  it('formata em português curto', () => {
    expect(tokensLabel(353)).toBe('353 tokens')
    expect(tokensLabel(1600)).toBe('1,6 mil tokens')
    expect(tokensLabel(1)).toBe('1 token')
  })

  it('vazio quando o número não é conhecido', () => {
    expect(tokensLabel(0)).toBe('')
    expect(tokensLabel(undefined)).toBe('')
    expect(tokensLabel(Number.NaN)).toBe('')
  })
})
