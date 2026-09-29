// Open dialogs and menus: the shortcut must not open the modal on top of them.
const OVERLAYS = '[role="dialog"], [role="alertdialog"], [aria-modal="true"], [role="menu"]'

function isHidden(el: Element): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) {
    if (node.hasAttribute('hidden') || node.getAttribute('aria-hidden') === 'true') return true
    if (getComputedStyle(node).display === 'none') return true
  }
  return false
}

function overlayOpen(): boolean {
  return Array.from(document.querySelectorAll(OVERLAYS)).some((el) => !isHidden(el))
}

/** "C" alone, outside any text field and with no dialog or menu open, opens the new conversation modal. */
export function shouldOpenNewConversation(event: KeyboardEvent): boolean {
  if (event.key !== 'c' || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false
  if (event.defaultPrevented || event.isComposing) return false
  if (overlayOpen()) return false
  const target = event.target as HTMLElement | null
  if (!target) return true
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false
  if (target.getAttribute?.('role') === 'textbox') return false
  // jsdom has no `isContentEditable`, so the property and the attribute are checked too.
  return !target.isContentEditable && target.contentEditable !== 'true' && target.getAttribute?.('contenteditable') !== 'true'
}
