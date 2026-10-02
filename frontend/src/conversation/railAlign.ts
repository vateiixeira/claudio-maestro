import type { ConversationItem } from '../types/conversation'
import { AGENT_TOOLS } from './turns'

/** Which kind of card sits next to a rail node; decides how far the dot is pushed down. */
export type RailAlign = 'text' | 'thinking' | 'notice' | 'bash' | 'agent' | 'group' | 'card'

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
  if (AGENT_TOOLS.has(item.name)) return 'agent'
  if (item.name === 'Bash') return 'bash'
  return 'card'
}
