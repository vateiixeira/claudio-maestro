import { describe, expect, it } from 'vitest'
import type { ToolItem } from '../../types/conversation'
import { GROUP_LABEL, workArtifacts, workFolders, workGroups, workSpan } from '../workGroups'
import { workKind } from '../work'

const done = { content: 'ok', is_error: false, details: null }
const failed = { content: 'boom', is_error: true, details: null }
function tool(id: string, name: string, input: Record<string, unknown> = {}, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id, tool_use_id: `tu-${id}`, name, input, result: done, streaming: false, parent_tool_use_id: null, ...extra }
}
const bash = (id: string, folder?: string) => tool(id, 'Bash', { command: folder ? `cd ${folder} && ls` : 'ls' })
function rowOf(item: ToolItem) {
  const folder = /^cd (\S+) &&/.exec(String(item.input.command ?? ''))?.[1]
  return { item, kind: workKind(item), folder }
}

describe('GROUP_LABEL', () => {
  it('um rótulo no plural por tipo', () => {
    expect(GROUP_LABEL).toEqual({
      bash: 'Comandos', read: 'Leituras', search: 'Buscas', edit: 'Edições', tool: 'Ferramenta', agent: 'Subagentes',
    })
  })
})

describe('workGroups', () => {
  it('junta linhas seguidas do mesmo tipo, pasta e ferramenta', () => {
    const rows = [
      bash('a', '/home/ana/dev/a'), bash('b', '/home/ana/dev/a'), bash('c', '/home/ana/dev/b'),
      tool('d', 'mcp__banco__query'), tool('e', 'mcp__banco__query'), tool('f', 'Read', { file_path: '/p/x' }),
    ].map(rowOf)
    const groups = workGroups(rows)
    expect(groups.map(({ label, where, rows: r }) => [label, where, r.length])).toEqual([
      ['Comandos', 'em ~/dev/a', 2], ['Comandos', 'em ~/dev/b', 1], ['Ferramenta', 'banco · query', 2], ['Leituras', '', 1],
    ])
    expect(groups.map((g) => g.key)).toEqual(['a', 'c', 'd', 'f'])
    expect(groups[0]!.kind).toBe('bash')
  })

  it('um comando sem cd não se junta a um com cd; ferramentas diferentes ficam em grupos separados', () => {
    expect(workGroups([bash('a'), bash('b', '/home/ana/dev/a')].map(rowOf))).toHaveLength(2)
    expect(workGroups([tool('a', 'mcp__banco__query'), tool('b', 'mcp__banco__ping')].map(rowOf))).toHaveLength(2)
  })

  it('o mesmo tipo separado por outro vira dois grupos; sem linhas, nenhum', () => {
    const r = [tool('a', 'Read'), tool('b', 'Grep'), tool('c', 'Read')].map(rowOf)
    expect(workGroups(r).map((g) => g.label)).toEqual(['Leituras', 'Buscas', 'Leituras'])
    expect(workGroups([])).toEqual([])
  })
})

describe('workFolders', () => {
  it('conta as pastas distintas dos cd', () => {
    expect(workFolders([bash('a', '/home/ana/dev/a'), bash('b', '/home/ana/dev/b'), bash('c', '/home/ana/dev/a')])).toBe(2)
    expect(workFolders([bash('a')])).toBe(0)
    expect(workFolders([tool('a', 'Read', { file_path: '/x' })])).toBe(0)
  })
})

describe('workSpan', () => {
  const at = (n: number) => tool(`t${n}`, 'Bash', {}, { at: n })
  it('do início da primeira ação até o fim, ou até agora enquanto roda', () => {
    expect(workSpan([at(100), at(120)], 138, 0, false)).toBe(38)
    expect(workSpan([at(100)], null, 112, true)).toBe(12)
  })

  it('nulo sem início, sem fim ou abaixo de 1 segundo', () => {
    expect(workSpan([at(100), at(120)], null, 0, false)).toBeNull()
    expect(workSpan([tool('s', 'Bash')], 138, 0, false)).toBeNull()
    expect(workSpan([at(100)], 100, 0, false)).toBeNull()
    expect(workSpan([], 100, 0, false)).toBeNull()
  })
})

describe('workArtifacts', () => {
  it('soma as edições por arquivo, na ordem em que aparecem', () => {
    const items = [
      tool('e1', 'Edit', { file_path: '/p/a.md', old_string: 'x\ny', new_string: 'a\nb\nc' }),
      tool('e2', 'Edit', { file_path: '/p/b.md', old_string: 'x', new_string: 'y' }),
      tool('e3', 'Edit', { file_path: '/p/a.md', old_string: '', new_string: 'a\nb' }),
      tool('r', 'Read', { file_path: '/p/c.md' }),
    ]
    const { files } = workArtifacts(items, false)
    expect(files).toEqual([
      { path: '/p/a.md', name: 'a.md', added: 5, removed: 2, itemId: 'e3' },
      { path: '/p/b.md', name: 'b.md', added: 1, removed: 1, itemId: 'e2' },
    ])
  })

  it('uma edição que falhou não entra', () => {
    const items = [tool('e1', 'Edit', { file_path: '/p/a.md', old_string: 'x', new_string: 'y' }, { result: failed })]
    expect(workArtifacts(items, false).files).toEqual([])
  })

  it('só entra a edição que deu certo, como na contagem do separador do turno', () => {
    const items = [
      tool('e1', 'Edit', { file_path: '/p/a.md', old_string: 'x', new_string: 'y' }),
      tool('e2', 'Edit', { file_path: '/p/b.md' }, { result: null }),
      tool('e3', 'Edit', { file_path: '/p/c.md' }, { result: null, result_missing: true }),
      tool('e4', 'Write', { file_path: '/p/d.md', content: 'x' }, { streaming: true }),
    ]
    expect(workArtifacts(items, true).files.map((file) => file.path)).toEqual(['/p/a.md'])
    expect(workArtifacts(items, false).files.map((file) => file.path)).toEqual(['/p/a.md'])
  })

  it('subagentes: duração, tokens e estado', () => {
    const sub = (extra = {}) => ({
      task_id: 't', subagent_type: 'Explore', description: 'Tarefa 1 · tela inicial', status: 'completed' as const,
      last_activity: null, usage: null, summary: null, ...extra,
    })
    const items = [
      tool('a1', 'Agent', {}, { subagent: sub({ usage: { total_tokens: 31000, duration_ms: 228000 } }) }),
      tool('a2', 'Agent', {}, { subagent: sub({ description: 'Outra', started_at: 100, last_activity_at: 160, status: 'running' }) }),
    ]
    expect(workArtifacts(items, false).agents).toEqual([
      { itemId: 'a1', description: 'Tarefa 1 · tela inicial', status: 'completed', seconds: 228, startedAt: null, tokens: 31000 },
      { itemId: 'a2', description: 'Outra', status: 'running', seconds: 60, startedAt: 100, tokens: null },
    ])
  })

  it('subagente sem dados de tempo fica com segundos nulos', () => {
    const { agents } = workArtifacts([tool('a', 'Agent', { description: 'd' })], false)
    expect(agents).toEqual([{ itemId: 'a', description: 'd', status: 'completed', seconds: null, startedAt: null, tokens: null }])
  })
})
