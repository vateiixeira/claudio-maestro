import { describe, expect, it } from 'vitest'
import { actionRow, buildTurns, groupChips, groupNodeKind, nodeKind, turnSummary } from '../turns'
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
    expect(turns[0]!.entries.map((e) => (e.kind === 'item' ? e.item.id : e.id))).toEqual(['a'])
    expect(turns[1]!.entries.map((e) => (e.kind === 'item' ? e.item.id : e.id))).toEqual(['b', 'c'])
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

describe('grupos de ações', () => {
  const ids = (turn: ReturnType<typeof buildTurns>[number]) =>
    turn.entries.map((e) => (e.kind === 'group' ? `G(${e.items.map((i) => i.id).join(',')})` : e.item.id))

  it('junta duas ou mais ações seguidas; uma sozinha continua item', () => {
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('g1', 'Grep'), tool('b1', 'Bash'), tool('s1', 'ToolSearch'), tool('m1', 'mcp__x__y'), text('x'), tool('r2', 'Read')])[0]!
    expect(ids(t)).toEqual(['G(r1,g1,b1,s1,m1)', 'x', 'r2'])
  })

  it('edição, subagente, tarefas, erro e texto quebram o grupo', () => {
    const err = tool('bx', 'Bash', {}, { result: { content: 'x', is_error: true, details: null } })
    const t = buildTurns([
      user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('e', 'Edit'), tool('r3', 'Read'), tool('r4', 'Read'),
      tool('a', 'Agent'), tool('r5', 'Read'), err, tool('r6', 'Read'), tool('t', 'TodoWrite'), tool('r7', 'Read'),
      { type: 'notice', id: 'n', level: 'warning', text: '' }, tool('r8', 'Read'),
      { type: 'thinking', id: 'th', text: '', streaming: false, parent_tool_use_id: null }, tool('r9', 'Read'),
    ])[0]!
    expect(ids(t)).toEqual(['G(r1,r2)', 'e', 'G(r3,r4)', 'a', 'r5', 'bx', 'r6', 't', 'r7', 'n', 'r8', 'th', 'r9'])
  })

  it('o id do grupo é o do primeiro item e não muda ao crescer', () => {
    const a = buildTurns([user('u'), tool('r1', 'Read'), tool('r2', 'Read')])[0]!
    const b = buildTurns([user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('r3', 'Bash')])[0]!
    expect(a.entries[0]).toMatchObject({ kind: 'group', id: 'r1' })
    expect(b.entries[0]).toMatchObject({ kind: 'group', id: 'r1' })
  })

  it('o resumo conta cada ação do grupo', () => {
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('b', 'Bash')])[0]!
    expect(turnSummary(t, () => []).actions).toBe(3)
  })

  it('chips com plural', () => {
    const items = [tool('a', 'Read'), tool('b', 'Read'), tool('c', 'Grep'), tool('d', 'Bash'), tool('e', 'Bash'), tool('f', 'Bash'), tool('g', 'ToolSearch')]
    expect(groupChips(items)).toEqual(['2 leituras', '1 busca', '3 comandos', '1 ferramenta'])
    expect(groupChips([tool('a', 'Glob'), tool('b', 'WebFetch'), tool('c', 'x'), tool('d', 'y')])).toEqual(['2 buscas', '2 ferramentas'])
  })

  it('nó do grupo: rodando se algum item roda', () => {
    expect(groupNodeKind([tool('a', 'Read'), tool('b', 'Read')], false)).toBe('group')
    expect(groupNodeKind([tool('a', 'Read'), tool('b', 'Read', {}, { result: null })], true)).toBe('running')
  })

  it('linha: rótulo, alvo e meta', () => {
    expect(actionRow(tool('a', 'Read', { file_path: '/p/a.py' }, { result: { content: 'x\ny\n', is_error: false, details: null } }), false))
      .toEqual({ label: 'Leitura', target: '/p/a.py', meta: '2 linhas' })
    expect(actionRow(tool('g', 'Grep', { pattern: 'foo', path: 'src' }), false)).toEqual({ label: 'Busca', target: 'foo em src', meta: '1 resultado' })
    expect(actionRow(tool('b', 'Bash', { command: 'ls' }, { result: null }), true)).toEqual({ label: 'Comando', target: 'ls', meta: 'rodando…' })
    expect(actionRow(tool('m', 'mcp__s__t', {}, { result: null }), false)).toEqual({ label: 'Ferramenta', target: 's · t', meta: 'sem resultado' })
    expect(actionRow(tool('x', 'ToolSearch', {}, { result: null, result_missing: true }), false).meta).toBe('Resultado não disponível no histórico')
  })
})
