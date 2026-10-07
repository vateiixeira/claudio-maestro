import { computed, inject, type ComputedRef } from 'vue'
import { SESSION_ID_KEY } from '../stores/changesPanel'
import { markdownFileRef, markdownViewHref } from './markdown'

/** Reader address for a tool's `file_path`: null when it is not a `.md` or the conversation is unknown. */
export function useMarkdownViewHref(getPath: () => string): ComputedRef<string | null> {
  const sessionId = inject(SESSION_ID_KEY, null)
  return computed(() => {
    const ref = markdownFileRef(getPath())
    return sessionId && ref ? markdownViewHref(sessionId.value, ref) : null
  })
}
