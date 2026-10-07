import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { computed } from 'vue'
import { SESSION_ID_KEY } from '../../../stores/changesPanel'
import TextBlock from '../TextBlock.vue'
import ReadTool from '../ReadTool.vue'
import EditTool from '../EditTool.vue'
import type { TextItem, ToolItem } from '../../../types/conversation'

const withSession = (id: string | null) => ({
  plugins: [createPinia()],
  provide: id ? { [SESSION_ID_KEY as symbol]: computed(() => id) } : {},
})

function text(t: string): TextItem {
  return { id: 't1', type: 'text', text: t, streaming: false, parent_tool_use_id: null }
}

function tool(name: string, file: string, headless = false) {
  const item: ToolItem = {
    id: 'x',
    type: 'tool',
    name,
    tool_use_id: 'u1',
    input: { file_path: file, content: 'a\n' },
    result: { content: 'a', is_error: false, details: null },
    streaming: false,
    parent_tool_use_id: null,
    result_missing: false,
  }
  return { item, headless }
}

describe('links de leitura no chat', () => {
  it('o texto do Claude liga caminhos .md à página de leitura da conversa', () => {
    const wrapper = mount(TextBlock, { props: { item: text('Escrevi em `docs/plano.md`.') }, global: withSession('s1') })
    expect(wrapper.find('a[data-md-view]').attributes('href')).toBe('/sessions/s1/ver?caminho=docs%2Fplano.md')
  })

  it('sem conversa não há link', () => {
    const wrapper = mount(TextBlock, { props: { item: text('`docs/plano.md`') }, global: withSession(null) })
    expect(wrapper.find('a[data-md-view]').exists()).toBe(false)
  })
})

describe('Ver nas ferramentas', () => {
  for (const [component, name] of [[ReadTool, 'Read'], [EditTool, 'Write']] as const) {
    it(`${name}: .md ganha Ver, no cabeçalho e sem cabeçalho`, () => {
      for (const headless of [false, true]) {
        const wrapper = mount(component, { props: tool(name, '/p/docs/plano.md', headless), global: withSession('s1') })
        const link = wrapper.find('[data-test="md-view"]')
        expect(link.attributes('href')).toBe('/sessions/s1/ver?caminho=%2Fp%2Fdocs%2Fplano.md')
        expect(link.attributes('target')).toBe('_blank')
        // Never inside the header button (a link inside a button is invalid and toggles the card).
        expect(link.element.closest('button')).toBeNull()
      }
    })

    it(`${name}: outros arquivos não ganham Ver`, () => {
      const wrapper = mount(component, { props: tool(name, '/p/a.py'), global: withSession('s1') })
      expect(wrapper.find('[data-test="md-view"]').exists()).toBe(false)
    })
  }
})
