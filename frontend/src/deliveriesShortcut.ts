import { isBareShortcut } from './keyboardShortcutGuard'

export type DeliveriesShortcut = 'prev' | 'next' | 'copy'

/**
 * The keys of "Entregas", outside text fields and with no dialog or menu open: the arrows change day and Shift+C
 * copies the day. A bare "C" stays with "Nova conversa".
 */
export function deliveriesShortcut(event: KeyboardEvent): DeliveriesShortcut | null {
  if (isBareShortcut(event, 'ArrowLeft')) return 'prev'
  if (isBareShortcut(event, 'ArrowRight')) return 'next'
  if (isBareShortcut(event, 'C', { shift: true })) return 'copy'
  return null
}
