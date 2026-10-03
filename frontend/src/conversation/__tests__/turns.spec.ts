import { describe, expect, it } from 'vitest'
import { buildTurns, nodeKind, tidyThinking, turnSummary } from '../turns'
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

const thought = (id: string, body: string, streaming = false): ConversationItem => ({ type: 'thinking', id, text: body, streaming, parent_tool_use_id: null })
const ids = (turn: ReturnType<typeof buildTurns>[number]) => turn.entries.map((e) => (e.kind === 'item' ? e.item.id : e.id))

describe('pensamentos nos turnos', () => {
  it('pensamentos seguidos viram um só: texto unido, id do primeiro, streaming do último', () => {
    const [turn] = buildTurns([user('u'), thought('t1', 'primeiro', false), thought('t2', 'segundo', true)])
    expect(turn!.entries).toHaveLength(1)
    const entry = turn!.entries[0]!
    expect(entry.kind).toBe('item')
    if (entry.kind !== 'item') return
    expect(entry.item).toMatchObject({ type: 'thinking', id: 't1', text: 'primeiro\n\nsegundo', streaming: true })
  })

  it('une três ou mais e não une pensamentos separados por outro item', () => {
    const [turn] = buildTurns([user('u'), thought('a', '1'), thought('b', '2'), thought('c', '3'), text('x'), thought('d', '4')])
    expect(ids(turn!)).toEqual(['a', 'x', 'd'])
    const first = turn!.entries[0]!
    expect(first.kind === 'item' && first.item.type === 'thinking' && first.item.text).toBe('1\n\n2\n\n3')
  })

  it('não une pensamentos de rodadas diferentes (separados por mensagem do usuário)', () => {
    const turns = buildTurns([user('u1'), thought('a', '1'), user('u2'), thought('b', '2')])
    expect(turns.map(ids)).toEqual([['a'], ['b']])
  })

  it('pensamento terminado e vazio ou só com espaços some', () => {
    const [turn] = buildTurns([user('u'), thought('e1', ''), thought('e2', ' \n '), text('x')])
    expect(ids(turn!)).toEqual(['x'])
  })

  it('pensamento vazio em andamento continua aparecendo', () => {
    const [turn] = buildTurns([user('u'), thought('e', '', true)])
    expect(ids(turn!)).toEqual(['e'])
  })

  it('pensamento vazio no meio não atrapalha a junção dos vizinhos', () => {
    const [turn] = buildTurns([user('u'), thought('a', 'um'), thought('v', ''), thought('b', 'dois')])
    expect(ids(turn!)).toEqual(['a'])
    const entry = turn!.entries[0]!
    expect(entry.kind === 'item' && entry.item.type === 'thinking' && entry.item.text).toBe('um\n\ndois')
  })

  it('terminado seguido de um em andamento vazio fica em andamento com o texto do primeiro', () => {
    const [turn] = buildTurns([user('u'), thought('a', 'um'), thought('b', '', true)])
    const entry = turn!.entries[0]!
    expect(entry.kind === 'item' && entry.item).toMatchObject({ id: 'a', text: 'um', streaming: true })
  })

  it('não altera os itens recebidos', () => {
    const a = thought('a', 'um')
    const b = thought('b', 'dois', true)
    buildTurns([user('u'), a, b])
    expect(a).toMatchObject({ text: 'um', streaming: false })
  })
})

describe('tidyThinking (filhos de subagentes)', () => {
  it('aplica a mesma regra a uma lista solta', () => {
    const out = tidyThinking([thought('a', 'um'), thought('v', ''), thought('b', 'dois'), tool('r', 'Read'), thought('z', '  ')])
    expect(out.map((i) => i.id)).toEqual(['a', 'r'])
    expect(out[0]).toMatchObject({ text: 'um\n\ndois' })
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
    // question and plan cards stand alone, with a plain dot
    expect(nodeKind(tool('q', 'AskUserQuestion'), false)).toBe('task')
    expect(nodeKind(tool('p', 'ExitPlanMode'), false)).toBe('task')
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

  it('o que espera o usuário vence o estado e o tipo', () => {
    const waiting = new Set(['tu-q', 'tu-b'])
    expect(nodeKind(tool('q', 'AskUserQuestion', {}, { result: null }), true, waiting)).toBe('waiting')
    expect(nodeKind(tool('b', 'Bash', {}, { result: null }), true, waiting)).toBe('waiting')
    expect(nodeKind(tool('x', 'Bash', {}, { result: null }), true, waiting)).toBe('running')
    expect(nodeKind(text('a'), true, new Set(['a']))).toBe('text')
  })

  it('Bash em background segue o status da tarefa, não o resultado do lançamento', () => {
    const result = { content: 'Command running in background with ID: b1.', is_error: false, details: null }
    const bg = (status: 'running' | 'completed' | 'failed' | 'stopped') => ({ task_id: 'b1', status, summary: null })
    expect(nodeKind(tool('b', 'Bash', {}, { result, background: bg('running') }), false)).toBe('running')
    expect(nodeKind(tool('b', 'Bash', {}, { result, background: bg('completed') }), true)).toBe('bash')
    expect(nodeKind(tool('b', 'Bash', {}, { result, background: bg('failed') }), false)).toBe('error')
  })
})

describe('blocos de trabalho', () => {
  const ids = (turn: ReturnType<typeof buildTurns>[number]) =>
    turn.entries.map((e) => (e.kind === 'group' ? `G(${e.items.map((i) => i.id).join(',')})` : e.item.id))

  it('junta todas as ações seguidas, de qualquer tipo; uma sozinha também vira bloco', () => {
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('g1', 'Grep'), tool('b1', 'Bash'), tool('s1', 'ToolSearch'), tool('m1', 'mcp__x__y'), text('x'), tool('r2', 'Read')])[0]!
    expect(ids(t)).toEqual(['G(r1,g1,b1,s1,m1)', 'x', 'G(r2)'])
  })

  it('edição, subagente e erro entram no bloco, na ordem', () => {
    const err = tool('bx', 'Bash', {}, { result: { content: 'x', is_error: true, details: null } })
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('e', 'Edit'), tool('w', 'Write'), tool('a', 'Agent'), err, tool('me', 'MultiEdit'), tool('n', 'NotebookEdit')])[0]!
    expect(ids(t)).toEqual(['G(r1,e,w,a,bx,me,n)'])
  })

  it('sequência mista: texto no meio separa os trechos', () => {
    const t = buildTurns([
      user('u'), tool('r1', 'Read'), tool('e1', 'Edit'), text('x'), tool('b1', 'Bash'), tool('a1', 'Agent'), tool('b2', 'Bash'), text('y'), text('z'), tool('g1', 'Grep'),
    ])[0]!
    expect(ids(t)).toEqual(['G(r1,e1)', 'x', 'G(b1,a1,b2)', 'y', 'z', 'G(g1)'])
  })

  it('texto, aviso, pensamento, tarefas, pergunta e plano quebram o bloco', () => {
    const t = buildTurns([
      user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('t', 'TodoWrite'), tool('r3', 'Read'), tool('tc', 'TaskCreate'), tool('r4', 'Read'),
      tool('q', 'AskUserQuestion'), tool('r5', 'Read'), tool('p', 'ExitPlanMode'), tool('r6', 'Read'),
      { type: 'notice', id: 'n', level: 'warning', text: '' }, tool('r7', 'Read'),
      { type: 'thinking', id: 'th', text: 'hmm', streaming: false, parent_tool_use_id: null }, tool('r8', 'Read'),
    ])[0]!
    expect(ids(t)).toEqual(['G(r1,r2)', 't', 'G(r3)', 'tc', 'G(r4)', 'q', 'G(r5)', 'p', 'G(r6)', 'n', 'G(r7)', 'th', 'G(r8)'])
  })

  it('a ferramenta que espera permissão (sem resultado) fica no bloco, no fim', () => {
    const waiting = tool('b2', 'Bash', { command: 'rm x' }, { result: null })
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('b1', 'Bash'), waiting])[0]!
    expect(ids(t)).toEqual(['G(r1,b1,b2)'])
    const group = t.entries[0]!
    expect(group.kind === 'group' && group.items[2]).toBe(waiting)
  })

  it('subagente com filhos: o bloco guarda só o subagente, e o resumo conta os filhos', () => {
    // Os filhos têm parent_tool_use_id e saem da lista de cima antes de buildTurns.
    const agent = tool('ag', 'Agent')
    const kids: Record<string, ConversationItem[]> = { 'tu-ag': [tool('k1', 'Edit', { file_path: '/p/a.py' }), tool('k2', 'Read'), text('kt')] }
    const t = buildTurns([user('u'), tool('r1', 'Read'), agent, tool('b1', 'Bash')])[0]!
    expect(ids(t)).toEqual(['G(r1,ag,b1)'])
    expect(turnSummary(t, (id) => kids[id] ?? [])).toEqual({ actions: 5, files: 1 })
  })

  it('um pensamento vazio, que não aparece, não quebra o bloco', () => {
    const empty: ConversationItem = { type: 'thinking', id: 'th', text: '', streaming: false, parent_tool_use_id: null }
    expect(ids(buildTurns([user('u'), tool('r1', 'Read'), empty, tool('r2', 'Read')])[0]!)).toEqual(['G(r1,r2)'])
  })

  it('cada turno tem os seus blocos: a mensagem do usuário separa', () => {
    const turns = buildTurns([user('u1'), tool('r1', 'Read'), user('u2'), tool('r2', 'Read'), tool('r3', 'Edit')])
    expect(turns.map(ids)).toEqual([['G(r1)'], ['G(r2,r3)']])
  })

  it('o id do bloco é o do primeiro item e não muda ao crescer', () => {
    const a = buildTurns([user('u'), tool('r1', 'Read')])[0]!
    const b = buildTurns([user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('r3', 'Bash')])[0]!
    expect(a.entries[0]).toMatchObject({ kind: 'group', id: 'r1' })
    expect(b.entries[0]).toMatchObject({ kind: 'group', id: 'r1' })
  })

  it('o resumo conta cada ação do bloco', () => {
    const t = buildTurns([user('u'), tool('r1', 'Read'), tool('r2', 'Read'), tool('b', 'Bash')])[0]!
    expect(turnSummary(t, () => []).actions).toBe(3)
  })
})
