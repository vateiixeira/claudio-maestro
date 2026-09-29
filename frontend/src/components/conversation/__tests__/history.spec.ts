import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationBlock from '../ConversationBlock.vue'
import type { ConversationItem } from '../../../types/conversation'

function tool(name: string, result: unknown, extra: Record<string, unknown> = {}): ConversationItem {
  return { type: 'tool', id: 't1', tool_use_id: 'tu1', name, input: { command: 'ls', file_path: '/a' }, result: result as never, streaming: false, parent_tool_use_id: null, ...extra } as ConversationItem
}

describe('itens do histórico', () => {
  it.each(['Bash', 'Read', 'Edit', 'Grep'])('%s sem resultado no histórico', (name) => {
    const w = mount(ConversationBlock, { props: { item: tool(name, null, { result_missing: true }), sessionActive: true } })
    expect(w.text()).toContain('Resultado não disponível no histórico')
    expect(w.text()).not.toContain('rodando')
    expect(w.text()).not.toContain('lendo')
    expect(w.text()).not.toContain('aplicando')
  })

  it('mensagem do usuário com anexos mostra marcadores', () => {
    const w = mount(ConversationBlock, { props: { item: {
      type: 'user', id: 'u', text: 'veja', images: [
        { type: 'image', media_type: 'image/png', size: 120 * 1024 },
        { type: 'document', media_type: 'application/pdf', size: 5000 },
      ],
    } } })
    const marks = w.findAll('[data-test="attachment"]').map((m) => m.text())
    expect(marks).toEqual(['Imagem · png · 120 KB', 'Documento PDF'])
  })

  it('imagem omitida no resultado', async () => {
    const w = mount(ConversationBlock, { props: { item: tool('Grep', {
      content: [{ type: 'text', text: 'antes' }, { type: 'image', omitted: true, media_type: 'image/png' }],
      is_error: false, details: null,
    }) } })
    await w.find('button').trigger('click')
    expect(w.text()).toContain('Imagem omitida')
    expect(w.text()).not.toContain('omitted')
  })
})
