import type { ConversationItem } from '../types/conversation'

/**
 * Which kind of card sits next to a rail node; decides how far the node is pushed down. Only what
 * stands alone in the rail is here: every action is inside a work block (`group`).
 */
export type RailAlign = 'text' | 'thinking' | 'notice' | 'group' | 'card'

/** Alignment by the card an item renders, never by its state (running/error fit any card). */
export function railAlign(item: ConversationItem): RailAlign {
  switch (item.type) {
    case 'text':
    case 'user':
      return 'text'
    case 'thinking':
      return 'thinking'
    case 'notice':
      return 'notice'
  }
  return 'card'
}
