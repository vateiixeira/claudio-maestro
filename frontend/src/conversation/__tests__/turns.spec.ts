import { describe, expect, it } from 'vitest'
import { buildTurns, nodeKind, turnSummary } from '../turns'
import type { ConversationItem, ToolItem } from '../../types/conversation'

const user = (id: string): ConversationItem => ({ type: 'user', id, text: id })
const text = (id: string): ConversationItem => ({ type: 'text', id, text: id, streaming: false, parent_tool_use_id: null })
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra }
}

describe('buildTurns', () => {
  it('abre um turno em cada mensagem do usuário', () => {
    const turns = buildTurns([user('u1'), text('a'), user('u2'), text('b'), text('c')])
    expect(turns).toHaveLength(2)
    expect(turns[0]!.user?.id).toBe('u1')
    expect(turns[0]!.entries.map((e) => e.item.id)).toEqual(['a'])
    expect(turns[1]!.entries.map((e) => e.item.id)).toEqual(['b', 'c'])
    expect(turns.map((t) => t.number)).toEqual([1, 2])
  })

  it('itens antes da primeira mensagem formam um turno sem mensagem', () => {
    const turns = buildTurns([text('a'), user('u1')])
    expect(turns).toHaveLength(2)
    expect(turns[0]!.user).toBeNull()
    expect(turns[1]!.entries).toEqual([])
  })

  it('sem itens, sem turnos', () => {
    expect(buildTurns([])).toEqual([])
  })
})

describe('turnSummary', () => {
  it('conta ações, inclusive dentro de subagentes, e arquivos distintos editados', () => {
    const agent = tool('ag', 'Agent')
    const kids: Record<string, ConversationItem[]> = {
      'tu-ag': [tool('k1', 'Edit', { file_path: '/p/a.py' }), tool('k2', 'Read', { file_path: '/p/b.py' }), text('kt')],
    }
    const turn = buildTurns([user('u'), tool('e1', 'Edit', { file_path: '/p/a.py' }), tool('w1', 'Write', { file_path: '/p/c.py' }), text('x'), agent])[0]!
    expect(turnSummary(turn, (id) => kids[id] ?? [])).toEqual({ actions: 5, files: 2 })
  })
})

describe('nodeKind', () => {
  it('classifica cada tipo', () => {
    expect(nodeKind(text('a'), false)).toBe('text')
    expect(nodeKind({ type: 'thinking', id: 't', text: '', streaming: false, parent_tool_use_id: null }, false)).toBe('thinking')
    expect(nodeKind(tool('r', 'Read'), false)).toBe('read')
    expect(nodeKind(tool('g', 'Grep'), false)).toBe('search')
    expect(nodeKind(tool('b', 'Bash'), false)).toBe('bash')
    expect(nodeKind(tool('e', 'MultiEdit'), false)).toBe('edit')
    expect(nodeKind(tool('t', 'TodoWrite'), false)).toBe('task')
    expect(nodeKind(tool('s', 'ToolSearch'), false)).toBe('tool')
    expect(nodeKind(tool('m', 'mcp__x__y'), false)).toBe('tool')
    expect(nodeKind(tool('a', 'Agent'), false)).toBe('agent')
    expect(nodeKind({ type: 'notice', id: 'n', level: 'warning', text: '' }, false)).toBe('warning')
    expect(nodeKind({ type: 'notice', id: 'n', level: 'info', text: '' }, false)).toBe('info')
    expect(nodeKind({ type: 'notice', id: 'n', level: 'error', text: '' }, false)).toBe('error')
  })

  it('ferramenta rodando e com erro', () => {
    expect(nodeKind(tool('b', 'Bash', {}, { result: null }), true)).toBe('running')
    expect(nodeKind(tool('b', 'Bash', {}, { result: null }), false)).toBe('bash')
    expect(nodeKind(tool('b', 'Bash', {}, { streaming: true }), false)).toBe('running')
    expect(nodeKind(tool('b', 'Bash', {}, { result: { content: 'x', is_error: true, details: null } }), false)).toBe('error')
    const sub = { task_id: null, subagent_type: null, description: null, last_activity: null, usage: null, summary: null }
    expect(nodeKind(tool('a', 'Agent', {}, { subagent: { ...sub, status: 'running' } }), true)).toBe('running')
    expect(nodeKind(tool('a', 'Agent', {}, { subagent: { ...sub, status: 'failed' } }), false)).toBe('error')
  })
})
