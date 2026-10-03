import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationBlock from '../ConversationBlock.vue'
import type { ToolItem } from '../../../types/conversation'

// Every action card opens with the same WorkHeader, in the tone of its kind.

function tool(name: string, input: Record<string, unknown>, extra: Partial<ToolItem> = {}): ToolItem {
  return { type: 'tool', id: 't1', tool_use_id: 'tu1', name, input, result: null, streaming: false, parent_tool_use_id: null, ...extra }
}
const ok = (content: unknown) => ({ content, is_error: false, details: null })
const failed = (content: unknown) => ({ content, is_error: true, details: null })
const show = (item: ToolItem, sessionActive = false) => mount(ConversationBlock, { props: { item, sessionActive } })
// The Bash card renames the header's data-test to "bash-header", so the kind is what finds them all
// (diff lines also carry a data-kind, with other values).
const HEADERS = ['bash', 'tool', 'read', 'search', 'edit', 'agent'].map((k) => `[data-kind="${k}"]`).join(',')
const header = (w: ReturnType<typeof show>) => w.find(HEADERS)
const state = (w: ReturnType<typeof show>) => w.find('[data-test="work-status"]')

describe('cabeçalho único das ações', () => {
  it.each([
    ['Bash', 'bash', 'Comando', 'text-type-command', { command: 'ls' }],
    ['Read', 'read', 'Leitura', 'text-type-file', { file_path: '/p/a.py' }],
    ['Edit', 'edit', 'Edição', 'text-type-file', { file_path: '/p/a.py', old_string: 'a', new_string: 'b' }],
    ['Write', 'edit', 'Escrita', 'text-type-file', { file_path: '/p/a.py', content: 'a' }],
    ['Grep', 'search', 'Busca', 'text-type-file', { pattern: 'x' }],
    ['NotebookEdit', 'tool', 'Ferramenta', 'text-type-command', { notebook_path: '/p/a.ipynb' }],
    ['Agent', 'agent', 'Subagente', 'text-type-agent', { description: 'x' }],
  ])('%s: tipo %s, rótulo "%s" e cor %s', (name, kind, label, tone, input) => {
    const w = show(tool(name, input))
    expect(w.findAll(HEADERS)).toHaveLength(1)
    expect(header(w).attributes('data-kind')).toBe(kind)
    expect(header(w).find('.cap').text()).toBe(label)
    expect(header(w).find('.cap').classes()).toContain(tone)
    expect(header(w).find('[data-test="work-icon"]').classes()).toContain(tone)
  })

  it('o erro deixa o ícone vermelho e escreve "falhou", em todos os tipos', () => {
    const items = [
      tool('Bash', { command: 'false' }, { result: failed('x') }),
      tool('Read', { file_path: '/a' }, { result: failed('x') }),
      tool('Edit', { file_path: '/a', old_string: 'a', new_string: 'b' }, { result: failed('x') }),
      tool('Grep', { pattern: 'x' }, { result: failed('x') }),
      tool('NotebookEdit', {}, { result: failed('x') }),
    ]
    for (const item of items) {
      const w = show(item)
      expect(state(w).attributes('data-status'), item.name).toBe('error')
      expect(state(w).text(), item.name).toBe('falhou')
      expect(header(w).find('[data-test="work-icon"]').classes(), item.name).toContain('text-diff-del-fg')
    }
  })

  it('sem resultado e resultado ausente do histórico não parecem rodando', () => {
    for (const name of ['Bash', 'Read', 'Grep', 'NotebookEdit']) {
      const idle = show(tool(name, { command: 'x', file_path: '/a', pattern: 'x' }))
      expect(state(idle).attributes('data-status'), name).toBe('idle')
      expect(idle.text(), name).toContain('sem resultado')
      const missing = show(tool(name, { command: 'x', file_path: '/a', pattern: 'x' }, { result_missing: true }), true)
      expect(state(missing).attributes('data-status'), name).toBe('idle')
      expect(missing.find('[data-test="result-missing"]').text(), name).toBe('Resultado não disponível no histórico')
    }
  })
})

describe('Read', () => {
  it('o caminho vai em mono na descrição e a contagem de linhas no estado', () => {
    const w = show(tool('Read', { file_path: '/p/a.py' }, { result: ok('l1\nl2\nl3') }))
    expect(header(w).find('[data-test="work-desc"]').text()).toBe('/p/a.py')
    expect(header(w).find('[data-test="work-desc"]').classes()).toContain('font-mono')
    expect(state(w).attributes('data-status')).toBe('ok')
    expect(state(w).find('[data-test="work-meta"]').text()).toBe('3 linhas')
    expect(header(w).find('[data-test="work-meta"]').exists()).toBe(true)
  })

  it('a linha inteira é o botão: chevron, aria-expanded e desligada sem resultado', async () => {
    const w = show(tool('Read', { file_path: '/p/a.py' }, { result: ok('l1') }))
    expect(header(w).element.tagName).toBe('BUTTON')
    expect(header(w).attributes('aria-expanded')).toBe('false')
    expect(header(w).find('[data-test="work-chevron"]').exists()).toBe(true)
    await header(w).trigger('click')
    expect(header(w).attributes('aria-expanded')).toBe('true')
    expect(w.text()).toContain('l1')
    const none = show(tool('Read', { file_path: '/p/a.py' }))
    expect(header(none).attributes('disabled')).toBeDefined()
  })
})

describe('Ferramenta genérica', () => {
  it('mostra o nome da ferramenta em mono e abre pela linha toda', async () => {
    const w = mount(ConversationBlock, { props: { item: tool('NotebookEdit', { pattern: 'foo' }, { result: ok('achou') }) }, attachTo: document.body })
    expect(header(w).find('[data-test="work-desc"]').text()).toContain('NotebookEdit')
    expect(header(w).find('[data-test="work-desc"]').classes()).toContain('font-mono')
    expect(header(w).element.tagName).toBe('BUTTON')
    expect(w.find('[data-test="tool-output"]').isVisible()).toBe(false)
    await header(w).trigger('click')
    expect(w.find('[data-test="tool-output"]').isVisible()).toBe(true)
  })

  it('a borda fica vermelha quando falhou', () => {
    const w = show(tool('NotebookEdit', {}, { result: failed('x') }))
    expect(w.find('[class*="border-diff-del-fg/40"]').exists()).toBe(true)
  })
})

describe('Busca', () => {
  it('sem link a linha é o botão; o nome da ferramenta vira o chip', async () => {
    const w = show(tool('Grep', { pattern: 'def', path: 'src' }, { result: ok('a\nb') }))
    expect(header(w).element.tagName).toBe('BUTTON')
    expect(header(w).find('[data-test="work-tag"]').text()).toBe('Grep')
    expect(header(w).find('[data-test="work-desc"]').text()).toBe('def')
    expect(header(w).text()).toContain('em src')
    expect(state(w).find('[data-test="work-meta"]').text()).toBe('2 resultados')
    await header(w).trigger('click')
    expect(w.text()).toContain('b')
  })

  it('com link a linha não é botão (link dentro de botão não funciona), e o chevron expande', async () => {
    const w = show(tool('WebFetch', { url: 'https://vuejs.org/guide' }, { result: ok('conteúdo') }))
    expect(header(w).element.tagName).toBe('DIV')
    expect(header(w).find('a').attributes('href')).toBe('https://vuejs.org/guide')
    const toggle = header(w).find('button')
    expect(toggle.attributes('aria-label')).toBe('Expandir resultado')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-label')).toBe('Recolher resultado')
    expect(w.text()).toContain('conteúdo')
  })
})

describe('Edição', () => {
  it('a linha não é botão e não tem chevron', () => {
    const w = show(tool('Edit', { file_path: '/p/a.py', old_string: 'a', new_string: 'b' }, { result: ok('feito') }))
    expect(header(w).element.tagName).toBe('DIV')
    expect(header(w).find('[data-test="work-chevron"]').exists()).toBe(false)
  })
})

describe('Subagente', () => {
  const sub = (status: 'running' | 'completed') => ({
    task_id: 'k', subagent_type: 'Explore', description: 'Mapear rotas', status, last_activity: null, usage: null, summary: null,
  })

  it('o cartão leva o tipo e o rótulo lilás; filho continua com o cabeçalho próprio', () => {
    const child = tool('Read', { file_path: '/p/c.py' }, { id: 'c', tool_use_id: 'tc', parent_tool_use_id: 'tu1', result: ok('x') })
    const w = mount(ConversationBlock, {
      props: { item: tool('Agent', {}, { subagent: sub('completed') }), childrenOf: (id: string) => (id === 'tu1' ? [child] : []) },
    })
    const headers = w.findAll(HEADERS)
    expect(headers.map((h) => h.attributes('data-kind'))).toEqual(['agent', 'read'])
  })
})
