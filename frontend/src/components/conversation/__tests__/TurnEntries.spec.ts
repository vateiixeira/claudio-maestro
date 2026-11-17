import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TurnEntries from '../TurnEntries.vue'
import WorkBlock from '../WorkBlock.vue'
import type { TurnEntry } from '../../../conversation/turns'
import type { TextItem, ToolItem } from '../../../types/conversation'

const done = { content: 'ok', is_error: false, details: null }
const tool = (id: string, at?: number): ToolItem => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name: 'Read', input: { file_path: '/p/a.md' }, result: done, streaming: false, parent_tool_use_id: null, ...(at != null ? { at } : {}),
})
const text = (id: string, at?: number): TextItem => ({ type: 'text', id, text: 'pronto', ...(at != null ? { at } : {}) } as TextItem)

function mountEntries(entries: TurnEntry[]) {
  return mount(TurnEntries, {
    props: {
      entries,
      sessionActive: false,
      waitingIds: new Set<string>(),
      childrenOf: () => [],
      taskList: null,
      isLive: () => false,
      isOpen: () => false,
    },
  })
}
const endAts = (w: ReturnType<typeof mountEntries>) => w.findAllComponents(WorkBlock).map((b) => b.props('endAt'))

describe('TurnEntries: fim do bloco de trabalho', () => {
  it('o grupo seguido de um texto recebe o horário do texto', () => {
    const w = mountEntries([
      { kind: 'group', id: 'a', items: [tool('a', 100)] },
      { kind: 'item', item: text('t', 138) },
    ])
    expect(endAts(w)).toEqual([138])
  })

  it('o último grupo do turno recebe null', () => {
    const w = mountEntries([
      { kind: 'group', id: 'a', items: [tool('a', 100)] },
      { kind: 'item', item: text('t', 138) },
      { kind: 'group', id: 'b', items: [tool('b', 140)] },
    ])
    expect(endAts(w)).toEqual([138, null])
  })

  it('a entrada seguinte sem horário dá null', () => {
    const w = mountEntries([
      { kind: 'group', id: 'a', items: [tool('a', 100)] },
      { kind: 'item', item: text('t') },
    ])
    expect(endAts(w)).toEqual([null])
  })

  it('um grupo seguido de outro grupo usa o horário do primeiro item do seguinte', () => {
    const w = mountEntries([
      { kind: 'group', id: 'a', items: [tool('a', 100)] },
      { kind: 'group', id: 'b', items: [tool('b', 150), tool('c', 160)] },
    ])
    expect(endAts(w)).toEqual([150, null])
  })
})
