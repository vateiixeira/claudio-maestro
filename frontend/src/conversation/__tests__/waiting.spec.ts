import { describe, expect, it } from 'vitest'
import type { ConversationItem, PermissionPrompt } from '../../types/conversation'
import { waitingIdsOf } from '../waiting'

const tool = (id: string, parent: string | null = null) =>
  ({ type: 'tool', id, tool_use_id: id, name: 'Bash', input: {}, result: null, streaming: false, parent_tool_use_id: parent }) as unknown as ConversationItem
const prompt = (toolUseId: string) => ({ prompt_id: `p-${toolUseId}`, tool_use_id: toolUseId }) as unknown as PermissionPrompt

describe('waitingIdsOf', () => {
  it('is empty without pending requests', () => {
    expect(waitingIdsOf([tool('a')], []).size).toBe(0)
  })

  it('has the tool of each pending request', () => {
    expect([...waitingIdsOf([tool('a'), tool('b')], [prompt('b')])]).toEqual(['b'])
  })

  it('includes the subagents the tool runs inside', () => {
    const items = [tool('outer'), tool('inner', 'outer'), tool('leaf', 'inner'), tool('other')]
    expect([...waitingIdsOf(items, [prompt('leaf')])].sort()).toEqual(['inner', 'leaf', 'outer'])
  })

  it('keeps the id of a request whose tool is not in the items', () => {
    expect([...waitingIdsOf([], [prompt('x')])]).toEqual(['x'])
  })

  it('does not loop on a cycle of parents', () => {
    expect([...waitingIdsOf([tool('a', 'b'), tool('b', 'a')], [prompt('a')])].sort()).toEqual(['a', 'b'])
  })
})
