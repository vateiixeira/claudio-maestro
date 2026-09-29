import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationBlock from '../ConversationBlock.vue'
import TruncatedText from '../TruncatedText.vue'
import type { ConversationItem } from '../../../types/conversation'

function tool(name: string, input: Record<string, unknown>, result: unknown = null): ConversationItem {
  return { type: 'tool', id: 't1', tool_use_id: 'tu1', name, input, result: result as never, streaming: false, parent_tool_use_id: null }
}
const mountItem = (item: ConversationItem, sessionActive = true) => mount(ConversationBlock, { props: { item, sessionActive } })

describe('blocos da conversa', () => {
  it('mensagem do usuário', () => {
    const w = mountItem({ type: 'user', id: 'u', text: 'faça X', images: [] })
    expect(w.find('[data-test="user-message"]').text()).toBe('faça X')
  })

  it('texto em markdown com indicação de streaming', () => {
    const w = mountItem({ type: 'text', id: 'x', text: '**forte** <b>cru</b>', streaming: true, parent_tool_use_id: null })
    expect(w.find('strong').text()).toBe('forte')
    expect(w.find('b').exists()).toBe(false)
    expect(w.find('[data-test="streaming"]').exists()).toBe(true)
  })

  it('raciocínio fica recolhido e expande', async () => {
    const w = mountItem({ type: 'thinking', id: 'x', text: 'pensando fundo', streaming: false, parent_tool_use_id: null })
    expect(w.text()).not.toContain('pensando fundo')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('pensando fundo')
  })

  it('Read mostra arquivo e linhas e expande o conteúdo', async () => {
    const w = mountItem(tool('Read', { file_path: '/p/a.py' }, { content: 'l1\nl2\nl3', is_error: false, details: null }))
    expect(w.text()).toContain('/p/a.py')
    expect(w.text()).toContain('3 linhas')
    expect(w.text()).not.toContain('l2')
    await w.find('button').trigger('click')
    expect(w.text()).toContain('l2')
  })

  it('Edit usa structuredPatch com números de linha', () => {
    const w = mountItem(tool('Edit', { file_path: '/p/a.py', old_string: 'x', new_string: 'y' }, {
      content: 'ok', is_error: false,
      details: { structuredPatch: [{ oldStart: 41, oldLines: 2, newStart: 41, newLines: 2, lines: [' ctx', '-velho', '+novo'] }] },
    }))
    expect(w.text()).toContain('+1')
    expect(w.text()).toContain('−1')
    const rows = w.findAll('[data-test="diff-line"]')
    expect(rows.map((r) => r.attributes('data-kind'))).toEqual(['context', 'del', 'add'])
    expect(rows[1]!.text()).toContain('42')
    expect(rows[1]!.text()).toContain('velho')
  })

  it('Edit sem resultado monta diff de old_string/new_string', () => {
    const w = mountItem(tool('Edit', { file_path: '/p/a.py', old_string: 'a\nb', new_string: 'a\nc' }))
    const rows = w.findAll('[data-test="diff-line"]')
    expect(rows.map((r) => r.attributes('data-kind'))).toEqual(['context', 'del', 'add'])
  })

  it('Bash rodando, com saída e com erro', async () => {
    const running = mountItem(tool('Bash', { command: 'pytest' }))
    expect(running.text()).toContain('$ pytest')
    expect(running.text()).toContain('rodando')

    const ok = mountItem(tool('Bash', { command: 'ls' }, { content: 'a.txt\nb.txt', is_error: false, details: null }))
    expect(ok.text()).toContain('b.txt')
    await ok.find('[data-test="toggle-output"]').trigger('click')
    expect(ok.text()).not.toContain('b.txt')

    const bad = mountItem(tool('Bash', { command: 'false' }, { content: 'falhou', is_error: true, details: null }))
    expect(bad.find('[data-test="tool-error"]').text()).toContain('falhou')
  })

  it('ferramenta genérica mostra nome, entrada e resultado em JSON', () => {
    const w = mountItem(tool('NotebookEdit', { pattern: 'foo' }, { content: [{ type: 'text', text: 'achou' }], is_error: false, details: null }))
    expect(w.text()).toContain('NotebookEdit')
    expect(w.text()).toContain('"pattern": "foo"')
    expect(w.text()).toContain('achou')
  })

  it('aviso com o nível', () => {
    const w = mountItem({ type: 'notice', id: 'n', level: 'error', text: 'deu ruim' })
    expect(w.find('[data-level="error"]').text()).toContain('deu ruim')
  })
})

describe('TruncatedText', () => {
  it('trunca em 200 linhas e mostra tudo ao pedir', async () => {
    const text = Array.from({ length: 250 }, (_, i) => `linha ${i + 1}`).join('\n')
    const w = mount(TruncatedText, { props: { text } })
    expect(w.text()).toContain('linha 200')
    expect(w.text()).not.toContain('linha 201')
    await w.find('[data-test="show-all"]').trigger('click')
    expect(w.text()).toContain('linha 250')
  })

  it('ferramenta sem resultado só aparece rodando com a sessão ativa ou em streaming', () => {
    for (const name of ['Bash', 'Read', 'Edit', 'Grep']) {
      const idle = mountItem(tool(name, { command: 'x', file_path: '/p/a.py' }), false)
      expect(idle.text()).not.toMatch(/rodando|lendo|aplicando/)
      if (name !== 'Edit') expect(idle.text()).toContain('sem resultado')
      const active = mountItem(tool(name, { command: 'x', file_path: '/p/a.py' }), true)
      expect(active.text()).toMatch(/rodando|lendo|aplicando/)
      const streaming = mountItem({ ...(tool(name, { command: 'x', file_path: '/p/a.py' }) as object), streaming: true } as ConversationItem, false)
      expect(streaming.text()).toMatch(/rodando|lendo|aplicando/)
    }
  })
})
