import type { InjectionKey, Ref } from 'vue'
import type { ConversationItem } from '../types/conversation'

/** The rule the backend search follows: no accents, no case, each run of whitespace as one space. */
export function normalizeForSearch(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/\s+/g, ' ').trim()
}

/**
 * Id of the last message of the main conversation (the user's or the model's text; not a subagent's,
 * not thinking) that contains `term`; null when none does.
 */
export function findLastMessage(items: ConversationItem[], term: string): string | null {
  const needle = normalizeForSearch(term)
  if (!needle) return null
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]!
    if (item.type !== 'user' && item.type !== 'text') continue
    if (item.type === 'text' && item.parent_tool_use_id) continue
    if (normalizeForSearch(item.text).includes(needle)) return item.id
  }
  return null
}

/** Id of the message the search just took the user to; the message with that id marks itself. */
export const MESSAGE_FOCUS_KEY: InjectionKey<Ref<string | null>> = Symbol('messageFocus')
