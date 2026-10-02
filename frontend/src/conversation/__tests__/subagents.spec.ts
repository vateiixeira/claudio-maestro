import { describe, expect, it } from 'vitest'
import { agentStatus, deriveSubagents, stripSubagents, summarizeSubagents, waitingText } from '../subagents'
import type { ConversationItem, Subagent, ToolItem } from '../../types/conversation'

const sub = (status: Subagent['status'], extra: Partial<Subagent> = {}): Subagent => ({
  task_id: 't', subagent_type: 'reviewer', description: 'Revisar', status, last_activity: null, usage: null, summary: null, ...extra,
})
const agent = (id: string, status: Subagent['status'] | null, extra: Partial<ToolItem> = {}): ToolItem => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Agent', input: { subagent_type: 'reviewer', description: `desc ${id}` },
  result: null, streaming: false, parent_tool_use_id: null, subagent: status ? sub(status, { description: `desc ${id}` }) : null, ...extra,
})
const tool = (id: string, name: string, input: Record<string, unknown>, parent: string | null): ToolItem => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: null, streaming: false, parent_tool_use_id: parent,
})
const user = (id: string): ConversationItem => ({ type: 'user', id, text: id })

describe('agentStatus', () => {
  it('usa o estado do subagente quando existe', () => {
    expect(agentStatus(agent('a', 'stopped'), true)).toBe('stopped')
  })
  it('sem subagente: erro, concluído ou rodando conforme o resultado e a sessão', () => {
    const base = agent('a', null)
    expect(agentStatus({ ...base, result: { content: 'x', is_error: true, details: null } }, true)).toBe('failed')
    expect(agentStatus({ ...base, result: { content: 'x', is_error: false, details: null } }, true)).toBe('completed')
    expect(agentStatus(base, false)).toBe('completed')
    expect(agentStatus(base, true)).toBe('running')
  })
})

describe('deriveSubagents', () => {
  it('lista tipo, descrição e estado', () => {
    const [entry] = deriveSubagents([user('u'), agent('a', 'running')], true)
    expect(entry).toMatchObject({ id: 'a', kind: 'reviewer', description: 'desc a', status: 'running' })
  })

  it('última ação: a ferramenta mais recente dentro do cartão, com alvo curto', () => {
    const items = [
      user('u'),
      agent('a', 'running'),
      tool('r', 'Read', { file_path: '/home/vi/dev/projeto/src/app.py' }, 'tu-a'),
      tool('g', 'Grep', { pattern: 'TODO', path: 'src' }, 'tu-a'),
    ]
    expect(deriveSubagents(items, true)[0]!.lastAction).toBe('Grep TODO')
    expect(deriveSubagents(items.slice(0, 3), true)[0]!.lastAction).toBe('Read app.py')
  })

  it('a última ação vem também de subagentes aninhados', () => {
    const items = [
      user('u'),
      agent('a', 'running'),
      agent('b', 'running', { parent_tool_use_id: 'tu-a' }),
      tool('c', 'Bash', { command: 'pytest -q\necho fim' }, 'tu-b'),
    ]
    const entries = deriveSubagents(items, true)
    expect(entries.map((e) => e.id)).toEqual(['a', 'b'])
    expect(entries[0]!.lastAction).toBe('Bash pytest -q')
    expect(entries[1]!.lastAction).toBe('Bash pytest -q')
  })

  it('alvo longo é encurtado', () => {
    const items = [user('u'), agent('a', 'running'), tool('c', 'Bash', { command: 'x'.repeat(200) }, 'tu-a')]
    const action = deriveSubagents(items, true)[0]!.lastAction
    expect(action.length).toBeLessThanOrEqual(70)
    expect(action.endsWith('…')).toBe(true)
  })

  it('sem ações filhas usa a atividade que o backend informou', () => {
    const item = agent('a', 'running')
    item.subagent = sub('running', { last_activity: 'Read' })
    expect(deriveSubagents([user('u'), item], true)[0]!.lastAction).toBe('Read')
    expect(deriveSubagents([user('u'), agent('b', 'running')], true)[0]!.lastAction).toBe('')
  })

  it('conjunto atual: o turno corrente e os que ainda rodam de turnos anteriores', () => {
    const items = [
      user('u1'), agent('old-done', 'completed'), agent('old-run', 'running'),
      user('u2'), agent('new-done', 'completed'), agent('new-run', 'running'),
    ]
    expect(deriveSubagents(items, true).map((e) => e.id)).toEqual(['old-run', 'new-done', 'new-run'])
  })

  it('ignora ferramentas que não são subagentes', () => {
    expect(deriveSubagents([user('u'), tool('r', 'Read', {}, null)], true)).toEqual([])
  })
})

describe('stripSubagents', () => {
  it('some quando nenhum roda e mantém os terminados enquanto algum roda', () => {
    const done = deriveSubagents([user('u'), agent('a', 'completed'), agent('b', 'failed')], true)
    expect(stripSubagents(done)).toEqual([])
    const mixed = deriveSubagents([user('u'), agent('a', 'completed'), agent('b', 'running')], true)
    expect(stripSubagents(mixed).map((e) => e.id)).toEqual(['a', 'b'])
  })
})

describe('summarizeSubagents', () => {
  it('conta por estado, com concordância', () => {
    const items = [
      user('u'), agent('a', 'running'), agent('b', 'running'), agent('c', 'running'),
      agent('d', 'completed'), agent('e', 'completed'), agent('f', 'failed'), agent('g', 'stopped'),
    ]
    expect(summarizeSubagents(deriveSubagents(items, true))).toBe('3 rodando, 2 concluídos, 1 com erro, 1 parado')
    expect(summarizeSubagents(deriveSubagents([user('u'), agent('a', 'running'), agent('d', 'completed')], true))).toBe('1 rodando, 1 concluído')
  })
})

const bg = (id: string, status: 'running' | 'completed' | 'failed' | 'stopped' | null, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Bash',
  input: { command: `sleep ${id}`, run_in_background: true, ...input },
  result: null, streaming: false, parent_tool_use_id: null,
  background: status ? { task_id: `b-${id}`, status, summary: null } : null, ...extra,
})

describe('comandos Bash em background na lista', () => {
  it('entram com o rótulo "Comando", a descrição (ou o comando cortado) e o estado', () => {
    const entries = deriveSubagents([
      user('u'),
      bg('a', 'running', { description: 'Subir o servidor' }),
      bg('b', 'completed', { command: 'x'.repeat(200) }),
    ], true)
    expect(entries[0]).toMatchObject({ id: 'a', type: 'command', kind: 'Comando', description: 'Subir o servidor', status: 'running', lastAction: '' })
    expect(entries[1]!.status).toBe('completed')
    expect(entries[1]!.description.length).toBeLessThanOrEqual(60)
    expect(entries[1]!.description.endsWith('…')).toBe(true)
  })

  it('subagentes continuam com type "agent" e a ordem do histórico se mantém', () => {
    const entries = deriveSubagents([user('u'), agent('a', 'running'), bg('b', 'running'), agent('c', 'completed')], true)
    expect(entries.map((e) => [e.id, e.type])).toEqual([['a', 'agent'], ['b', 'command'], ['c', 'agent']])
  })

  it('mesma regra do conjunto atual: turno corrente e turnos anteriores só se ainda rodam', () => {
    const items = [
      user('u1'), bg('old-done', 'completed'), bg('old-run', 'running'), bg('old-failed', 'failed'),
      user('u2'), bg('new-done', 'completed'), bg('new-run', 'running'),
    ]
    expect(deriveSubagents(items, false).map((e) => e.id)).toEqual(['old-run', 'new-done', 'new-run'])
  })

  it('sem status ao vivo (histórico) e Bash comum não entram', () => {
    const items = [user('u'), bg('hist', null), bg('plain', null, { run_in_background: false }), bg('live', 'running')]
    expect(deriveSubagents(items, true).map((e) => e.id)).toEqual(['live'])
  })

  it('a faixa aparece enquanto um comando roda, e só ele basta', () => {
    expect(stripSubagents(deriveSubagents([user('u'), bg('a', 'running')], false)).map((e) => e.id)).toEqual(['a'])
    expect(stripSubagents(deriveSubagents([user('u'), bg('a', 'completed')], false))).toEqual([])
  })

  it('o resumo conta comandos e subagentes juntos', () => {
    expect(summarizeSubagents(deriveSubagents([user('u'), agent('a', 'running'), bg('b', 'running'), bg('c', 'completed')], true))).toBe('2 rodando, 1 concluído')
  })
})

describe('waitingText', () => {
  const run = (type: 'agent' | 'command') => ({ id: 'x', type, kind: '', description: '', status: 'running' as const, lastAction: '' })
  it('só comandos: singular e plural', () => {
    expect(waitingText([run('command')])).toBe('Aguardando 1 comando em background')
    expect(waitingText([run('command'), run('command')])).toBe('Aguardando 2 comandos em background')
  })
  it('só subagentes: singular e plural', () => {
    expect(waitingText([run('agent')])).toBe('Aguardando 1 subagente em background')
    expect(waitingText([run('agent'), run('agent'), run('agent')])).toBe('Aguardando 3 subagentes em background')
  })
  it('misturados viram "tarefas"', () => {
    expect(waitingText([run('agent'), run('command')])).toBe('Aguardando 2 tarefas em background')
  })
})
