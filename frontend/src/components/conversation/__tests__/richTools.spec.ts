import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationBlock from '../ConversationBlock.vue'
import type { ConversationItem, Subagent, ToolItem } from '../../../types/conversation'
import { deriveTasks } from '../../../conversation/tasks'

function tool(name: string, input: Record<string, unknown>, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id: extra.id ?? 't1', tool_use_id: 'tu1', name, input, result: null, streaming: false, parent_tool_use_id: null, ...extra }
}
const ok = (content: unknown) => ({ content, is_error: false, details: null })
const sub = (overrides: Partial<Subagent> = {}): Subagent => ({
  task_id: 'k1', subagent_type: 'Explore', description: 'Mapear rotas', status: 'running',
  last_activity: 'Lendo app.py', usage: { total_tokens: 12345, tool_uses: 7, duration_ms: 65000 }, summary: null, ...overrides,
})
const child = (id: string, name: string): ConversationItem =>
  tool(name, { file_path: `/p/${id}.py` }, { id, tool_use_id: `c-${id}`, parent_tool_use_id: 'tu1' })

describe('subagente', () => {
  it.each([
    ['running', 'Rodando'],
    ['completed', 'Concluído'],
    ['failed', 'Com erro'],
    ['stopped', 'Parado'],
  ] as const)('estado %s', (status, label) => {
    const w = mount(ConversationBlock, { props: { item: tool('Agent', { description: 'x' }, { subagent: sub({ status }) }) } })
    const state = w.find('[data-test="subagent-state"]')
    expect(state.attributes('data-status')).toBe(status)
    expect(state.attributes('aria-label')).toBe(label)
  })

  it('mostra tipo, descrição, atividade, métricas e resumo', () => {
    const w = mount(ConversationBlock, { props: { item: tool('Task', {}, { subagent: sub({ status: 'completed', summary: 'Achei 3 rotas' }) }) } })
    const t = w.text()
    expect(t).toContain('Explore')
    expect(t).toContain('Mapear rotas')
    expect(t).toContain('7 ferramentas')
    expect(t).toContain('12.345 tokens')
    expect(t).toContain('1 min 5 s')
    expect(t).toContain('Achei 3 rotas')
    const running = mount(ConversationBlock, { props: { item: tool('Agent', {}, { subagent: sub() }) } })
    expect(running.text()).toContain('Lendo app.py')
  })

  it('filhos dentro do cartão, abertos enquanto roda e em tempo real', async () => {
    const children = [child('a', 'Read')]
    const w = mount(ConversationBlock, { props: { item: tool('Agent', {}, { subagent: sub() }), childrenOf: (id: string) => (id === 'tu1' ? children : []) } })
    expect(w.findAll('[data-test="subagent-children"] > *')).toHaveLength(1)
    children.push(child('b', 'Grep'))
    await w.setProps({ childrenOf: (id: string) => (id === 'tu1' ? [...children] : []) })
    expect(w.findAll('[data-test="subagent-children"] > *')).toHaveLength(2)
  })

  it('recolhe ao concluir e respeita a escolha manual', async () => {
    const children = (id: string) => (id === 'tu1' ? [child('a', 'Read')] : [])
    const w = mount(ConversationBlock, { props: { item: tool('Agent', {}, { subagent: sub() }), childrenOf: children }, attachTo: document.body })
    const visible = () => w.find('[data-test="subagent-children"]').isVisible()
    expect(visible()).toBe(true)
    await w.setProps({ item: tool('Agent', {}, { subagent: sub({ status: 'completed' }) }) })
    expect(visible()).toBe(false)
    await w.find('[data-test="subagent-toggle"]').trigger('click')
    expect(visible()).toBe(true)
    await w.setProps({ item: tool('Agent', {}, { subagent: sub({ status: 'completed', summary: 'fim' }) }) })
    expect(visible()).toBe(true)
  })
})

describe('blocos de busca', () => {
  it('Grep mostra padrão, caminho e contagem, e expande', async () => {
    const w = mount(ConversationBlock, { props: { item: tool('Grep', { pattern: 'def \\w+', path: 'src' }, { result: ok('a.py\nb.py') }) } })
    expect(w.text()).toContain('def \\w+')
    expect(w.text()).toContain('src')
    expect(w.text()).toContain('2 resultados')
    expect(w.text()).not.toContain('b.py')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('b.py')
  })

  it('Glob mostra padrão e contagem', () => {
    const w = mount(ConversationBlock, { props: { item: tool('Glob', { pattern: '**/*.ts' }, { result: ok('x.ts') }) } })
    expect(w.text()).toContain('**/*.ts')
    expect(w.text()).toContain('1 resultado')
  })

  it('WebSearch mostra a consulta e expande resultados', async () => {
    const w = mount(ConversationBlock, { props: { item: tool('WebSearch', { query: 'vue 3 slots' }, { result: ok('Resultado A') }) } })
    expect(w.text()).toContain('vue 3 slots')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('Resultado A')
  })

  it('WebFetch com URL http vira link seguro', () => {
    const w = mount(ConversationBlock, { props: { item: tool('WebFetch', { url: 'https://vuejs.org/guide' }) } })
    const a = w.find('a')
    expect(a.attributes('href')).toBe('https://vuejs.org/guide')
    expect(a.attributes('rel')).toBe('noopener noreferrer')
    expect(a.attributes('target')).toBe('_blank')
  })

  it('WebFetch com javascript: não vira link', () => {
    const w = mount(ConversationBlock, { props: { item: tool('WebFetch', { url: 'javascript:alert(1)' }) } })
    expect(w.find('a').exists()).toBe(false)
    expect(w.text()).toContain('javascript:alert(1)')
  })

  it('ToolSearch com resultado não diz "Carregando"', () => {
    const w = mount(ConversationBlock, { props: { item: tool('ToolSearch', { query: 'q' }, { result: ok('ok') }) } })
    expect(w.text()).not.toContain('Carregando')
  })

  it('ToolSearch é discreto', () => {
    const w = mount(ConversationBlock, { props: { item: tool('ToolSearch', { query: 'select:TaskCreate' }) } })
    expect(w.find('[data-test="tool-search"]').exists()).toBe(true)
    expect(w.find('button').exists()).toBe(false)
  })
})

describe('lista de tarefas', () => {
  const items: ConversationItem[] = [
    tool('TaskCreate', { subject: 'Criar tabela', description: 'd' }, { id: 'a', result: ok('Task #1 created successfully: Criar tabela') }),
    tool('TaskCreate', { subject: 'Escrever testes' }, { id: 'b', result: ok('Task #2 created successfully') }),
    tool('TaskUpdate', { taskId: '1', status: 'completed' }, { id: 'c' }),
    tool('TaskUpdate', { taskId: '2', status: 'in_progress' }, { id: 'd' }),
  ]

  it('consolida TaskCreate e TaskUpdate na ordem', () => {
    expect(deriveTasks(items)).toEqual({
      lastItemId: 'd',
      tasks: [
        { id: '1', subject: 'Criar tabela', status: 'completed' },
        { id: '2', subject: 'Escrever testes', status: 'in_progress' },
      ],
    })
  })

  it('TaskCreate sem resultado não casa com TaskUpdate de outra tarefa', () => {
    const r = deriveTasks([
      tool('TaskCreate', { subject: 'Sem id' }, { id: 'a' }),
      tool('TaskUpdate', { taskId: '1', status: 'completed' }, { id: 'b' }),
    ])
    expect(r.tasks).toHaveLength(1)
    expect(r.tasks[0]!.status).toBe('pending')
  })

  it('lista aparece no bloco certo dentro de um subagente', () => {
    const inner = tool('TaskUpdate', { taskId: '1', status: 'in_progress' }, { id: 'u', tool_use_id: 'c-u', parent_tool_use_id: 'tu1' })
    const all = [items[0]!, inner]
    const w = mount(ConversationBlock, {
      props: {
        item: tool('Agent', {}, { subagent: sub() }),
        childrenOf: (id: string) => (id === 'tu1' ? [inner] : []),
        taskList: deriveTasks(all),
      },
    })
    const rows = w.findAll('[data-test="task-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('Em andamento')
  })

  it('TodoWrite substitui a lista', () => {
    const r = deriveTasks([...items, tool('TodoWrite', { todos: [{ content: 'Só isto', status: 'pending' }] }, { id: 'e' })])
    expect(r.lastItemId).toBe('e')
    expect(r.tasks).toEqual([{ id: '1', subject: 'Só isto', status: 'pending' }])
  })

  it('bloco mostra a tarefa e o estado; o último mostra a lista', () => {
    const create = mount(ConversationBlock, { props: { item: items[0]! as ToolItem } })
    expect(create.text()).toContain('Criar tabela')
    expect(create.text()).toContain('Pendente')
    const { tasks } = deriveTasks(items)
    const last = mount(ConversationBlock, { props: { item: items[3]! as ToolItem, tasks } })
    const rows = last.findAll('[data-test="task-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('Concluída')
    expect(rows[1]!.text()).toContain('Em andamento')
    expect(last.text()).toContain('Escrever testes')
  })
})

describe('cartão genérico', () => {
  it('MCP mostra nome legível', () => {
    const w = mount(ConversationBlock, { props: { item: tool('mcp__github__create_issue', { title: 'x' }) } })
    expect(w.text()).toContain('github · create_issue')
    expect(w.text()).not.toContain('mcp__')
  })
})
