import { describe, expect, it } from 'vitest'
import { groupNodeKind, workActivity, workRow, workStatus, workSummary } from '../work'
import type { ToolItem } from '../../types/conversation'

const done = { content: 'ok', is_error: false, details: null }
const failed = { content: 'boom', is_error: true, details: null }
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false, parent_tool_use_id: null, ...extra }
}
const sub = (status: 'running' | 'completed' | 'failed' | 'stopped', extra = {}) => ({
  task_id: 't', subagent_type: 'Explore', description: 'achar o bug', status, last_activity: null, usage: null, summary: null, ...extra,
})

describe('workStatus', () => {
  it('ok, rodando, erro, parado e sem resultado', () => {
    expect(workStatus(tool('a', 'Read'), false)).toBe('ok')
    expect(workStatus(tool('a', 'Read', {}, { result: null }), true)).toBe('running')
    expect(workStatus(tool('a', 'Read', {}, { result: null }), false)).toBe('idle')
    expect(workStatus(tool('a', 'Read', {}, { result: null, result_missing: true }), true)).toBe('idle')
    expect(workStatus(tool('a', 'Bash', {}, { streaming: true }), false)).toBe('running')
    expect(workStatus(tool('a', 'Bash', {}, { result: failed }), false)).toBe('error')
  })

  it('subagente segue o próprio estado', () => {
    expect(workStatus(tool('a', 'Agent', {}, { subagent: sub('running') }), false)).toBe('running')
    expect(workStatus(tool('a', 'Agent', {}, { subagent: sub('completed') }), true)).toBe('ok')
    expect(workStatus(tool('a', 'Agent', {}, { subagent: sub('failed') }), false)).toBe('error')
    expect(workStatus(tool('a', 'Agent', {}, { subagent: sub('stopped') }), false)).toBe('stopped')
    expect(workStatus(tool('a', 'Agent', {}, { result: null }), true)).toBe('running')
    expect(workStatus(tool('a', 'Agent'), false)).toBe('ok')
  })

  it('Bash em background segue a tarefa, não o lançamento', () => {
    const bg = (status: 'running' | 'completed' | 'failed' | 'stopped') => ({ task_id: 'b', status, summary: null })
    expect(workStatus(tool('b', 'Bash', {}, { background: bg('running') }), false)).toBe('running')
    expect(workStatus(tool('b', 'Bash', {}, { background: bg('completed') }), true)).toBe('ok')
    expect(workStatus(tool('b', 'Bash', {}, { background: bg('failed') }), false)).toBe('error')
    expect(workStatus(tool('b', 'Bash', {}, { background: bg('stopped') }), false)).toBe('stopped')
    expect(workStatus(tool('b', 'Bash', { run_in_background: true }), false)).toBe('ok')
  })
})

describe('workRow', () => {
  it('leitura: arquivo e número de linhas', () => {
    expect(workRow(tool('r', 'Read', { file_path: '/p/a.py' }, { result: { ...done, content: 'x\ny\n' } }), false))
      .toMatchObject({ kind: 'read', desc: '/p/a.py', mono: true, status: 'ok', meta: '2 linhas' })
  })

  it('busca: ferramenta como etiqueta, assunto e pasta; Grep e Glob contam resultados', () => {
    expect(workRow(tool('g', 'Grep', { pattern: 'foo', path: 'src' }), false))
      .toMatchObject({ kind: 'search', tag: 'Grep', desc: 'foo em src', meta: '1 resultado' })
    expect(workRow(tool('w', 'WebFetch', { url: 'https://x.dev' }), false))
      .toMatchObject({ kind: 'search', tag: 'WebFetch', desc: 'https://x.dev' })
  })

  it('edição: arquivo, rótulo de Write e contagem de linhas', () => {
    const edit = workRow(tool('e', 'Edit', { file_path: '/p/a.py', old_string: 'a\nb', new_string: 'c' }), false)
    expect(edit).toMatchObject({ kind: 'edit', desc: '/p/a.py', diff: { added: 1, removed: 2 } })
    expect(edit.label).toBeUndefined()
    expect(workRow(tool('w', 'Write', { file_path: '/p/n.py', content: 'x' }), false).label).toBe('Escrita')
  })

  it('comando: a descrição vira o título e o comando vai para a segunda linha', () => {
    expect(workRow(tool('b', 'Bash', { command: 'pytest -q\nls', description: 'Roda os testes' }), false))
      .toMatchObject({ kind: 'bash', desc: 'Roda os testes', mono: false, command: 'pytest -q' })
    expect(workRow(tool('b', 'Bash', { command: 'pytest -q\nls' }), false))
      .toMatchObject({ kind: 'bash', desc: 'pytest -q', mono: true })
    expect(workRow(tool('b', 'Bash', { command: 'pytest -q\nls' }), false).command).toBeUndefined()
  })

  it('subagente: tipo como etiqueta e descrição', () => {
    expect(workRow(tool('a', 'Agent', { description: 'x' }, { subagent: sub('running') }), true))
      .toMatchObject({ kind: 'agent', tag: 'Explore', desc: 'achar o bug', status: 'running' })
    expect(workRow(tool('a', 'Agent', { description: 'do input', subagent_type: 'Plan' }), false))
      .toMatchObject({ tag: 'Plan', desc: 'do input' })
  })

  it('outras ferramentas: o nome, com servidor e ferramenta no MCP', () => {
    expect(workRow(tool('m', 'mcp__s__t'), false)).toMatchObject({ kind: 'tool', desc: 's · t' })
  })

  it('sem resultado e resultado ausente no histórico', () => {
    expect(workRow(tool('m', 'ToolSearch', {}, { result: null }), false).meta).toBe('sem resultado')
    expect(workRow(tool('m', 'ToolSearch', {}, { result: null, result_missing: true }), false).meta).toBe('Resultado não disponível no histórico')
  })
})

describe('workSummary', () => {
  it('conta por tipo, com "ok" nos comandos e as falhas à parte', () => {
    const items = [
      tool('e', 'Edit', { file_path: '/a' }),
      tool('b', 'Bash', { command: 'ls' }),
      tool('x', 'Read', {}, { result: failed }),
    ]
    expect(workSummary(items, false)).toBe('1 edição · 1 comando ok · 1 falhou')
  })

  it('plural, ordem fixa e falhas no plural', () => {
    const items = [
      tool('a', 'Agent'), tool('b', 'Bash'), tool('c', 'Bash'), tool('d', 'Edit'), tool('e', 'MultiEdit'),
      tool('f', 'Read'), tool('g', 'Grep'), tool('h', 'mcp__s__t'),
      tool('i', 'Bash', {}, { result: failed }), tool('j', 'Edit', {}, { result: failed }),
    ]
    expect(workSummary(items, false)).toBe('1 leitura · 1 busca · 2 edições · 2 comandos ok · 1 ferramenta · 1 subagente · 2 falharam')
  })

  it('o que roda aparece como "rodando" e sai da contagem do tipo', () => {
    const items = [tool('a', 'Read'), tool('b', 'Bash', {}, { result: null })]
    expect(workSummary(items, true)).toBe('1 leitura · 1 rodando')
    expect(workSummary(items, false)).toBe('1 leitura · 1 comando ok')
  })
})

describe('workActivity', () => {
  it('é vazia sem nada rodando', () => {
    expect(workActivity([tool('a', 'Read')], true)).toBe('')
  })

  it('mostra a última ação em andamento', () => {
    const items = [
      tool('a', 'Bash', { command: 'sleep 9' }, { result: null }),
      tool('b', 'Read', { file_path: '/p/a.py' }, { result: null }),
    ]
    expect(workActivity(items, true)).toBe('Leitura · /p/a.py')
  })

  it('de subagente, usa a última atividade dele', () => {
    const item = tool('a', 'Agent', { description: 'd' }, { subagent: sub('running', { last_activity: 'Grep foo' }) })
    expect(workActivity([item], true)).toBe('Subagente · Grep foo')
    expect(workActivity([tool('a', 'Agent', {}, { subagent: sub('running') })], true)).toBe('Subagente · achar o bug')
  })
})

describe('groupNodeKind', () => {
  const running = (name: string) => tool('run', name, {}, { result: null })
  const failedTool = tool('f', 'Bash', {}, { result: failed })

  it('sem estado a dizer, é o tipo da primeira ação', () => {
    expect(groupNodeKind([tool('a', 'Read'), tool('b', 'Bash')], false)).toBe('read')
    expect(groupNodeKind([tool('a', 'Grep')], false)).toBe('search')
    expect(groupNodeKind([tool('a', 'Write')], false)).toBe('edit')
    expect(groupNodeKind([tool('a', 'Agent')], false)).toBe('agent')
    expect(groupNodeKind([tool('a', 'mcp__x__y'), tool('b', 'Read')], false)).toBe('tool')
    expect(groupNodeKind([tool('a', 'Bash')], false)).toBe('bash')
  })

  it('rodando vence o tipo e o erro', () => {
    expect(groupNodeKind([tool('a', 'Read'), running('Read')], true)).toBe('running')
    expect(groupNodeKind([failedTool, running('Read')], true)).toBe('running')
  })

  it('erro vence o tipo, ainda que a ação que falhou não seja a primeira', () => {
    expect(groupNodeKind([tool('a', 'Read'), failedTool], false)).toBe('error')
    expect(groupNodeKind([tool('a', 'Agent', {}, { subagent: sub('failed') })], false)).toBe('error')
  })

  it('esperando o usuário vence tudo', () => {
    const waiting = new Set(['tu-run'])
    expect(groupNodeKind([tool('a', 'Read'), running('Bash')], true, waiting)).toBe('waiting')
    expect(groupNodeKind([failedTool, running('Bash')], true, waiting)).toBe('waiting')
    expect(groupNodeKind([tool('a', 'Read')], true, waiting)).toBe('read')
  })
})

describe('ferramenta esperando o usuário', () => {
  const waiting = new Set(['tu-w'])
  const pending = () => tool('w', 'Bash', { command: 'rm -rf x' }, { result: null })

  it('workStatus é "waiting", mesmo com a ferramenta sem resultado (que seria "running")', () => {
    expect(workStatus(pending(), true)).toBe('running')
    expect(workStatus(pending(), true, waiting)).toBe('waiting')
    expect(workStatus(tool('o', 'Read'), true, waiting)).toBe('ok')
  })

  it('o subagente que contém o pedido também espera', () => {
    const agent = tool('w', 'Agent', {}, { subagent: sub('running') })
    expect(workStatus(agent, true, waiting)).toBe('waiting')
  })

  it('workRow leva o estado', () => {
    expect(workRow(pending(), true, waiting).status).toBe('waiting')
  })

  it('o resumo conta "esperando você" no lugar de "rodando"', () => {
    const items = [tool('a', 'Read'), pending()]
    expect(workSummary(items, true, waiting)).toBe('1 leitura · 1 esperando você')
    expect(workSummary([...items, tool('r', 'Bash', {}, { result: null })], true, waiting)).toBe('1 leitura · 1 rodando · 1 esperando você')
    expect(workSummary([pending(), tool('w2', 'Bash', {}, { result: null })], true, new Set(['tu-w', 'tu-w2']))).toBe('2 esperando você')
  })

  it('a linha de atividade do bloco fechado continua dizendo qual é a ação', () => {
    expect(workActivity([pending()], true, waiting)).toBe('Comando · rm -rf x')
  })
})
