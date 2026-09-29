import { describe, expect, it } from 'vitest'
import { shouldOpenNewConversation } from '../newConversationShortcut'

function key(init: KeyboardEventInit, target: HTMLElement = document.body) {
  const event = new KeyboardEvent('keydown', init)
  Object.defineProperty(event, 'target', { value: target })
  return event
}

describe('atalho C', () => {
  it('abre com C fora de campos de texto', () => {
    expect(shouldOpenNewConversation(key({ key: 'c' }))).toBe(true)
    expect(shouldOpenNewConversation(key({ key: 'C', shiftKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c', ctrlKey: true }))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('textarea')))).toBe(false)
    expect(shouldOpenNewConversation(key({ key: 'c' }, document.createElement('input')))).toBe(false)
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    expect(shouldOpenNewConversation(key({ key: 'c' }, editable))).toBe(false)
  })
})
