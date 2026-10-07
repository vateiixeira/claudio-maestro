// Open dialogs and menus: a single-key shortcut must not fire from under them.
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

/**
 * Whether `event` is the bare `key` (no modifiers), not already handled or composing, with no dialog or menu open
 * and the focus outside any text field. Shared by the single-key shortcuts of the app. With `shift`, Shift is the
 * one modifier required (the `key` is then the shifted character, like "C").
 */
export function isBareShortcut(event: KeyboardEvent, key: string, options: { shift?: boolean } = {}): boolean {
  if (event.key !== key || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey !== (options.shift ?? false)) return false
  if (event.defaultPrevented || event.isComposing) return false
  if (overlayOpen()) return false
  const target = event.target as HTMLElement | null
  if (!target) return true
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false
  // The focus may sit on a child of the editable element (inherited editing), so look up the tree.
  if (target.closest?.('[role="textbox"]')) return false
  const editable = target.closest?.('[contenteditable]')
  if (editable && editable.getAttribute('contenteditable') !== 'false') return false
  // jsdom has no `isContentEditable`, so the property and the attribute are checked too.
  return !target.isContentEditable && target.contentEditable !== 'true'
}
