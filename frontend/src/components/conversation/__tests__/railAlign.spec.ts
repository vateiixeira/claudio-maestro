import { describe, expect, it } from 'vitest'
import { railAlign } from '../../../conversation/railAlign'
import type { ConversationItem } from '../../../types/conversation'

const tool = (name: string, extra: object = {}) =>
  ({ type: 'tool', id: 't', tool_use_id: 'tu', name, input: {}, result: null, ...extra }) as unknown as ConversationItem

describe('railAlign', () => {
  it('depende do cartão, não do estado', () => {
    expect(railAlign({ type: 'text', id: 'x', text: 'a' } as ConversationItem)).toBe('text')
    expect(railAlign({ type: 'thinking', id: 'x', text: 'a', streaming: false } as ConversationItem)).toBe('thinking')
    for (const level of ['info', 'warning', 'error']) {
      expect(railAlign({ type: 'notice', id: 'n', level, text: 'a' } as ConversationItem)).toBe('notice')
    }
    expect(railAlign(tool('Bash'))).toBe('bash')
    expect(railAlign(tool('Bash', { result: { content: 'x', is_error: true, details: null } }))).toBe('bash')
    expect(railAlign(tool('Agent'))).toBe('agent')
    expect(railAlign(tool('Task'))).toBe('agent')
    expect(railAlign(tool('Read'))).toBe('card')
    expect(railAlign(tool('Edit'))).toBe('card')
    expect(railAlign(tool('WebFetch'))).toBe('card')
  })
})
