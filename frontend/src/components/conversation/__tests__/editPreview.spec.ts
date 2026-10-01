import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EditTool from '../EditTool.vue'
import type { ToolItem } from '../../../types/conversation'

function tool(name: string, input: Record<string, unknown>, details: Record<string, unknown> | null = null): ToolItem {
  return {
    type: 'tool', id: 't1', tool_use_id: 'tu1', name, input,
    result: { content: 'ok', is_error: false, details }, streaming: false, parent_tool_use_id: null,
  } as ToolItem
}
const numbered = (n: number, prefix = 'linha') => Array.from({ length: n }, (_, i) => `${prefix} ${i + 1}`).join('\n')
const mountTool = (item: ToolItem) => mount(EditTool, { props: { item } })

describe('Write de arquivo novo', () => {
  it('mostra prévia neutra de 12 linhas, sem gutter de mais e sem fundo verde', () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: numbered(30) }))
    expect(w.find('[data-test="diff-line"]').exists()).toBe(false)
    const preview = w.find('[data-test="new-file-preview"]')
    expect(preview.exists()).toBe(true)
    expect(preview.text()).toContain('linha 12')
    expect(preview.text()).not.toContain('linha 13')
    expect(preview.html()).not.toContain('bg-diff-add-bg')
    expect(preview.html()).not.toContain('text-diff-add-fg')
    expect(preview.classes().join(' ') + preview.find('pre').classes().join(' ')).toContain('text-fg-muted')
    expect(preview.find('pre').classes()).toContain('whitespace-pre-wrap')
    expect(preview.text()).not.toContain('+')
  })

  it('rodapé informa o total e "Ver tudo" expande o restante', async () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: numbered(30) }))
    expect(w.find('[data-test="new-file-footer"]').text()).toContain('Novo arquivo · 30 linhas')
    const button = w.find('[data-test="show-lines"]')
    expect(button.text()).toBe('Ver tudo')
    await button.trigger('click')
    expect(w.find('[data-test="new-file-preview"]').text()).toContain('linha 30')
    expect(w.find('[data-test="show-lines"]').exists()).toBe(false)
    expect(w.find('[data-test="collapse"]').exists()).toBe(true)
  })

  it('arquivo curto não tem botão', () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: numbered(5) }))
    expect(w.find('[data-test="show-lines"]').exists()).toBe(false)
    expect(w.find('[data-test="new-file-footer"]').text()).toContain('Novo arquivo · 5 linhas')
  })

  it('mantém o limite de 200 linhas com aviso e "Ver tudo (N linhas)"', async () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: numbered(250) }))
    await w.find('[data-test="show-lines"]').trigger('click')
    const preview = w.find('[data-test="new-file-preview"]')
    expect(preview.text()).toContain('linha 200')
    expect(preview.text()).not.toContain('linha 201')
    expect(w.text()).toContain('Mostrando 200 de 250 linhas')
    await w.find('[data-test="show-all"]').trigger('click')
    expect(w.find('[data-test="new-file-preview"]').text()).toContain('linha 250')
  })

  it('o caminho continua em info-soft no cabeçalho', () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: 'a' }))
    expect(w.find('span.text-info-soft').text()).toBe('/p/novo.md')
  })

  it('Write sobre arquivo existente continua como diff', () => {
    const w = mountTool(tool('Write', { file_path: '/p/a.md', content: 'novo' }, {
      structuredPatch: [{ oldStart: 1, oldLines: 1, newStart: 1, newLines: 1, lines: ['-velho', '+novo'] }],
    }))
    expect(w.find('[data-test="new-file-preview"]').exists()).toBe(false)
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(2)
  })
})

describe('Edit com diff grande', () => {
  const big = (n: number) => tool('Edit', { file_path: '/p/a.py', old_string: '', new_string: '' }, {
    structuredPatch: [{
      oldStart: 1, oldLines: n, newStart: 1, newLines: n,
      lines: Array.from({ length: n }, (_, i) => (i % 2 ? `+nova ${i}` : `-velha ${i}`)),
    }],
  })

  it('mostra até 40 linhas e "Ver as N linhas" expande', async () => {
    const w = mountTool(big(100))
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(40)
    const button = w.find('[data-test="show-lines"]')
    expect(button.text()).toBe('Ver as 100 linhas')
    await button.trigger('click')
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(100)
    expect(w.find('[data-test="collapse"]').exists()).toBe(true)
  })

  it('mantém o limite de 200 linhas e "Ver tudo"', async () => {
    const w = mountTool(big(250))
    await w.find('[data-test="show-lines"]').trigger('click')
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(200)
    await w.find('[data-test="show-all"]').trigger('click')
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(250)
  })

  it('diff pequeno não tem botão e mantém as cores de diff', () => {
    const w = mountTool(big(10))
    expect(w.find('[data-test="show-lines"]').exists()).toBe(false)
    expect(w.html()).toContain('bg-diff-add-bg')
    expect(w.html()).toContain('bg-diff-del-bg')
  })

  it('o bloco de linhas rola na horizontal', () => {
    const w = mountTool(big(3))
    expect(w.find('[data-test="diff-line"]').element.parentElement!.className).toContain('overflow-x-auto')
  })

  it('usa o tipo do backend: "create" é arquivo novo mesmo com detalhes completos', () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: 'a\nb' }, {
      type: 'create',
      structuredPatch: [{ oldStart: 1, oldLines: 0, newStart: 1, newLines: 2, lines: ['+a', '+b'] }],
    }))
    expect(w.find('[data-test="new-file-preview"]').exists()).toBe(true)
  })

  it('tipo "update" continua como diff mesmo quando todas as linhas são adições', () => {
    const w = mountTool(tool('Write', { file_path: '/p/a.md', content: 'a\nb' }, {
      type: 'update',
      structuredPatch: [{ oldStart: 1, oldLines: 0, newStart: 1, newLines: 2, lines: ['+a', '+b'] }],
    }))
    expect(w.find('[data-test="new-file-preview"]').exists()).toBe(false)
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(2)
  })

  it('Write que terminou em erro nunca é tratado como arquivo novo', () => {
    const item = tool('Write', { file_path: '/p/novo.md', content: numbered(5) }, { type: 'create' })
    item.result!.is_error = true
    const w = mountTool(item)
    expect(w.find('[data-test="new-file-preview"]').exists()).toBe(false)
    expect(w.find('[data-test="new-file-footer"]').exists()).toBe(false)
    const bare = tool('Write', { file_path: '/p/novo.md', content: numbered(5) })
    bare.result!.is_error = true
    expect(mountTool(bare).find('[data-test="new-file-preview"]').exists()).toBe(false)
  })

  it('rodapé usa o singular com uma linha só', () => {
    const w = mountTool(tool('Write', { file_path: '/p/novo.md', content: 'unica' }))
    expect(w.find('[data-test="new-file-footer"]').text()).toBe('Novo arquivo · 1 linha')
  })
})
