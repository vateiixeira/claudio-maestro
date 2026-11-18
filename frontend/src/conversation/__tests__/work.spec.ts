import { describe, expect, it } from 'vitest'
import { groupNodeKind, hasUnrecoveredFailure, workActivity, workCaption, workFailure, workRetries, workRow, workStatus } from '../work'
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

  it('comando com cd: a pasta sai do comando', () => {
    expect(workRow(tool('b', 'Bash', { command: 'cd /home/ana/dev/a && ls', description: 'Listar' }), false))
      .toMatchObject({ desc: 'Listar', command: 'ls', folder: '/home/ana/dev/a', mono: false })
    expect(workRow(tool('b', 'Bash', { command: 'cd /home/ana/dev/a && pwd' }), false))
      .toMatchObject({ desc: 'pwd', mono: true, folder: '/home/ana/dev/a' })
    expect(workRow(tool('b', 'Bash', { command: 'pwd' }), false).folder).toBeUndefined()
  })

  it('ferramenta com entrada de texto: a primeira linha dela, em monoespaçada', () => {
    expect(workRow(tool('m', 'mcp__banco__query', { query: 'select 1\nfrom t' }), false))
      .toMatchObject({ kind: 'tool', desc: 'select 1', mono: true })
    expect(workRow(tool('m', 'mcp__banco__ping'), false)).toMatchObject({ desc: 'banco · ping' })
  })

  it('sem resultado e resultado ausente no histórico', () => {
    expect(workRow(tool('m', 'ToolSearch', {}, { result: null }), false).meta).toBe('sem resultado')
    expect(workRow(tool('m', 'ToolSearch', {}, { result: null, result_missing: true }), false).meta).toBe('Resultado não disponível no histórico')
  })
})

describe('workCaption', () => {
  it('resume por tipo, contando também as ações que falharam', () => {
    const items = [
      tool('e', 'Edit', { file_path: '/a' }),
      tool('b', 'Bash', { command: 'ls' }),
      tool('x', 'Read', {}, { result: failed }),
    ]
    expect(workCaption(items, false)).toBe('Executou 1 comando, fez 1 leitura, editou a')
  })

  it('plural e ordem fixa', () => {
    const items = [
      tool('a', 'Agent'), tool('b', 'Bash'), tool('c', 'Bash'), tool('d', 'Edit'), tool('e', 'MultiEdit'),
      tool('f', 'Read'), tool('g', 'Grep'), tool('h', 'mcp__s__t'),
      tool('i', 'Bash', {}, { result: failed }), tool('j', 'Edit', {}, { result: failed }),
    ]
    expect(workCaption(items, false)).toBe('Executou 3 comandos, fez 1 leitura, fez 3 edições, fez 1 busca, usou 1 ferramenta, executou 1 subagente')
  })

  it('a atividade substitui o resumo enquanto executa', () => {
    const items = [tool('a', 'Read'), tool('b', 'Bash', {}, { result: null })]
    expect(workCaption(items, true)).toBe('Comando')
    expect(workCaption(items, false)).toBe('Fez 1 leitura, 1 ação sem resultado')
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

  it('a espera pelo usuário prevalece sobre a execução', () => {
    const items = [tool('a', 'Read'), pending()]
    expect(workCaption(items, true, waiting)).toBe('Esperando você')
    expect(workCaption([...items, tool('r', 'Bash', {}, { result: null })], true, waiting)).toBe('Esperando você')
    expect(workCaption([pending(), tool('w2', 'Bash', {}, { result: null })], true, new Set(['tu-w', 'tu-w2']))).toBe('Esperando você')
  })

  it('a linha de atividade do bloco fechado continua dizendo qual é a ação', () => {
    expect(workActivity([pending()], true, waiting)).toBe('Comando · rm -rf x')
  })
})

describe('workRow de escrita feita por subagente', () => {
  it('mostra a origem no chip', () => {
    const row = workRow(tool('w', 'Write', { file_path: '/p/a.py', content: 'x' }, { parent_tool_use_id: 'tu-ag' }), false, undefined, 'reviewer')
    expect(row.kind).toBe('edit')
    expect(row.label).toBe('Escrita')
    expect(row.tag).toBe('reviewer')
    expect(row.desc).toBe('/p/a.py')
  })

  it('sem origem, a edição não tem chip', () => {
    expect(workRow(tool('e', 'Edit', { file_path: '/p/a.py' }), false).tag).toBeUndefined()
  })

  it('a origem só vale para edição', () => {
    expect(workRow(tool('r', 'Read', { file_path: '/p/a.py' }), false, undefined, 'reviewer').tag).toBeUndefined()
  })
})

describe('workRow: leitura de imagem', () => {
  it('uma leitura que só devolveu imagens diz quantas, não "0 linhas"', () => {
    const marker = (index: number) => ({ type: 'image', omitted: true, media_type: 'image/png', index, size: 1 })
    const read = (content: unknown) => tool('a', 'Read', { file_path: '/p/a.png' }, { result: { content, is_error: false, details: null } })
    expect(workRow(read([marker(0)]), false).meta).toBe('1 imagem')
    expect(workRow(read([marker(0), marker(1)]), false).meta).toBe('2 imagens')
    expect(workRow(read([{ type: 'text', text: 'a\nb' }, marker(0)]), false).meta).toBe('2 linhas')
  })
})

describe('novas tentativas', () => {
  const bashItem = (id: string, command: string, extra: Partial<ToolItem> = {}) => tool(id, 'Bash', { command }, extra)
  const erro = (id: string, command = 'grep x') => bashItem(id, command, { result: failed })

  it('workRetries liga a falha à ação seguinte do mesmo tipo (e do mesmo programa no Bash)', () => {
    expect(workRetries([erro('a'), bashItem('b', 'grep y')], false)).toEqual(new Map([['a', 'b']]))
    expect(workRetries([erro('a'), bashItem('b', 'cd /p && grep y')], false)).toEqual(new Map([['a', 'b']]))
    expect(workRetries([erro('a'), bashItem('b', 'ls')], false).size).toBe(0)
    expect(workRetries([
      tool('a', 'mcp__banco__query', {}, { result: failed }), tool('b', 'mcp__banco__query'),
    ], false)).toEqual(new Map([['a', 'b']]))
    expect(workRetries([tool('a', 'Read', {}, { result: failed }), tool('b', 'Read', {}, { result: failed })], false).size).toBe(0)
  })

  it('só a ação seguinte conta, e subagente nunca', () => {
    expect(workRetries([erro('a'), tool('r', 'Read'), bashItem('b', 'grep y')], false).size).toBe(0)
    const agent = (id: string, status: 'failed' | 'completed') => tool(id, 'Agent', {}, { subagent: sub(status) })
    expect(workRetries([agent('a', 'failed'), agent('b', 'completed')], false).size).toBe(0)
  })

  it('workFailure diz quantas falharam e se foram refeitas', () => {
    const ok = (id: string) => bashItem(id, 'grep y')
    expect(workFailure([erro('a'), ok('b')], false)).toBe('1 falhou, refeita em seguida')
    expect(workFailure([erro('a'), ok('b'), erro('c'), ok('d')], false)).toBe('2 falharam, refeitas em seguida')
    expect(workFailure([erro('a'), ok('b'), erro('c', 'ls')], false)).toBe('2 falharam')
    expect(workFailure([ok('a')], false)).toBe('')
    expect(workFailure([erro('a'), erro('b', 'ls')], false)).toBe('2 falharam')
  })

  it('uma nova tentativa que ainda não deu certo não conta como refeita', () => {
    const rodando = bashItem('b', 'grep y', { result: null })
    expect(workFailure([erro('a'), rodando], true)).toBe('1 falhou')
    expect(workFailure([erro('a'), erro('b', 'grep z')], false)).toBe('2 falharam')
  })

  it('uma edição de outro arquivo não refaz a falha; a do mesmo arquivo sim', () => {
    const edit = (id: string, file: string, extra: Partial<ToolItem> = {}) => tool(id, 'Edit', { file_path: file }, extra)
    const falha = edit('a', '/p/a.py', { result: failed })
    expect(workRetries([falha, edit('b', '/p/b.py')], false).size).toBe(0)
    expect(workFailure([falha, edit('b', '/p/b.py')], false)).toBe('1 falhou')
    expect(hasUnrecoveredFailure([falha, edit('b', '/p/b.py')], false)).toBe(true)
    expect(groupNodeKind([falha, edit('b', '/p/b.py')], false)).toBe('error')
    expect(workRetries([falha, edit('b', '/p/a.py')], false)).toEqual(new Map([['a', 'b']]))
    const nb = (id: string, file: string, extra: Partial<ToolItem> = {}) => tool(id, 'NotebookEdit', { notebook_path: file }, extra)
    expect(workRetries([nb('a', '/p/n.ipynb', { result: failed }), nb('b', '/p/m.ipynb')], false).size).toBe(0)
    expect(workRetries([nb('a', '/p/n.ipynb', { result: failed }), nb('b', '/p/n.ipynb')], false).size).toBe(1)
  })

  it('git push seguido de git status não é nova tentativa; o mesmo subcomando é', () => {
    const falha = erro('a', 'git push origin x')
    expect(workRetries([falha, bashItem('b', 'git status')], false).size).toBe(0)
    expect(workFailure([falha, bashItem('b', 'git status')], false)).toBe('1 falhou')
    expect(hasUnrecoveredFailure([falha, bashItem('b', 'git status')], false)).toBe(true)
    expect(groupNodeKind([falha, bashItem('b', 'git status')], false)).toBe('error')
    expect(workRetries([falha, bashItem('b', 'git --no-pager push --force')], false)).toEqual(new Map([['a', 'b']]))
    expect(workRetries([erro('a', 'pnpm test'), bashItem('b', 'pnpm build')], false).size).toBe(0)
    expect(workRetries([erro('a', 'pytest'), bashItem('b', 'pytest -x')], false).size).toBe(1)
    expect(workRetries([erro('a', 'grep x'), bashItem('b', 'grep y')], false).size).toBe(1)
  })

  it.each([
    ['uv run pytest', 'uv run ruff check'],
    ['pnpm --dir frontend test', 'pnpm --dir frontend build'],
    ['git -C /p/app push', 'git -C /p/app status'],
    ['pnpm exec vitest run', 'pnpm exec vue-tsc -b'],
    ['npm run test', 'npm run lint'],
    ['docker compose up', 'docker compose logs'],
    ['pnpm --filter=app test', 'pnpm --filter=app build'],
  ])('"%s" seguido de "%s" não é nova tentativa', (first, second) => {
    const falha = erro('m1:0', first)
    const next = () => bashItem('m2:0', second)
    expect(workRetries([falha, next()], false).size).toBe(0)
    expect(workFailure([falha, next()], false)).toBe('1 falhou')
    expect(hasUnrecoveredFailure([falha, next()], false)).toBe(true)
    expect(groupNodeKind([falha, next()], false)).toBe('error')
  })

  it.each([
    ['uv run pytest', 'uv run pytest -x'],
    ['pnpm --dir frontend test', 'pnpm --dir frontend test --retry 1'],
    ['git -C /p/app push', 'git -C /p/app push --force'],
    ['pnpm --dir a exec vitest run x', 'pnpm --dir a exec vitest run y'],
    ['grep x', 'grep y'],
    ['pytest', 'pytest -x'],
  ])('"%s" seguido de "%s" é nova tentativa', (first, second) => {
    expect(workRetries([erro('m1:0', first), bashItem('m2:0', second)], false).size).toBe(1)
  })

  it('chamadas paralelas (da mesma mensagem) não são nova tentativa', () => {
    const batch = (id: string, command: string, extra: Partial<ToolItem> = {}) => bashItem(id, command, extra)
    const falha = batch('msg1:1', 'grep x', { result: failed })
    expect(workRetries([falha, batch('msg1:2', 'grep y')], false).size).toBe(0)
    expect(workFailure([falha, batch('msg1:2', 'grep y')], false)).toBe('1 falhou')
    expect(hasUnrecoveredFailure([falha, batch('msg1:2', 'grep y')], false)).toBe(true)
    expect(groupNodeKind([falha, batch('msg1:2', 'grep y')], false)).toBe('error')
    expect(workRetries([falha, batch('msg2:0', 'grep y')], false)).toEqual(new Map([['msg1:1', 'msg2:0']]))
  })

  it('a nova tentativa em andamento deixa a falha pendente, não pendurada', () => {
    const rodando = bashItem('b', 'pytest -x', { result: null })
    const falha = erro('a', 'pytest')
    expect(hasUnrecoveredFailure([falha, rodando], true)).toBe(false)
    expect(groupNodeKind([falha, rodando], true)).toBe('running')
    expect(hasUnrecoveredFailure([falha, rodando], true, new Set(['tu-b']))).toBe(false)
    expect(groupNodeKind([falha, rodando], true, new Set(['tu-b']))).toBe('waiting')
    expect(workFailure([falha, rodando], true)).toBe('1 falhou')
    expect(hasUnrecoveredFailure([falha, bashItem('b', 'pytest -x')], false)).toBe(false)
    expect(hasUnrecoveredFailure([falha, erro('b', 'pytest -x')], false)).toBe(true)
  })

  it('hasUnrecoveredFailure', () => {
    expect(hasUnrecoveredFailure([erro('a'), bashItem('b', 'grep y')], false)).toBe(false)
    expect(hasUnrecoveredFailure([erro('a')], false)).toBe(true)
    expect(hasUnrecoveredFailure([tool('a', 'Agent', {}, { subagent: sub('failed') })], false)).toBe(true)
    expect(hasUnrecoveredFailure([tool('a', 'Read')], false)).toBe(false)
  })

  it('o nó do bloco só vira erro com falha sem nova tentativa', () => {
    expect(groupNodeKind([erro('a'), bashItem('b', 'grep y')], false)).toBe('bash')
    expect(groupNodeKind([erro('a')], false)).toBe('error')
  })
})
