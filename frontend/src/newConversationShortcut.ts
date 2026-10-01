import { isBareShortcut } from './keyboardShortcutGuard'

/** "C" alone, outside any text field and with no dialog or menu open, opens the new conversation modal. */
export function shouldOpenNewConversation(event: KeyboardEvent): boolean {
  return isBareShortcut(event, 'c')
}
