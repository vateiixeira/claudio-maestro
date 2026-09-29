/** "C" alone, outside any text field, opens the new conversation modal. */
export function shouldOpenNewConversation(event: KeyboardEvent): boolean {
  if (event.key !== 'c' || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false
  const target = event.target as HTMLElement | null
  if (!target) return true
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false
  // jsdom has no `isContentEditable`, so the property and the attribute are checked too.
  return !target.isContentEditable && target.contentEditable !== 'true' && target.getAttribute?.('contenteditable') !== 'true'
}
