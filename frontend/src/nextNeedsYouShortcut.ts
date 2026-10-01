import { isBareShortcut } from './keyboardShortcutGuard'

/** "N" alone, outside any text field and with no dialog or menu open, goes to the next conversation that waits for the user. */
export function shouldGoToNextNeedsYou(event: KeyboardEvent): boolean {
  return isBareShortcut(event, 'n')
}
