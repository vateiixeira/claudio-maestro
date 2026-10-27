import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { request } from '../api/http'

/** Persisted session + message UUID provenance. Text is never used as evidence. */
export function useMessageOrigins(sessionId: Readonly<Ref<string>>, messageIds: Readonly<Ref<string[]>>) {
  const automatic = ref<Set<string>>(new Set())
  let ticket = 0, currentSession = sessionId.value
  async function refresh() {
    const mine = ++ticket, id = sessionId.value, ids = [...messageIds.value]
    if (id !== currentSession) { currentSession = id; automatic.value = new Set() }
    if (!ids.length) { automatic.value = new Set(); return }
    try {
      const pages = []
      for (let index = 0; index < ids.length; index += 200) {
        const query = new URLSearchParams({ session_id: id })
        for (const messageId of ids.slice(index, index + 200)) query.append('message_ids', messageId)
        pages.push(await request<{ items: { message_id: string; origin: 'automation' }[] }>('GET', `/api/work/message-origins?${query}`))
      }
      if (mine === ticket) automatic.value = new Set(pages.flatMap(page => page.items.filter(item => item.origin === 'automation').map(item => item.message_id)))
    } catch { /* Unknown provenance stays visible as the original message. */ }
  }
  watch(() => JSON.stringify([sessionId.value, ...messageIds.value]), () => { void refresh() }, { immediate: true })
  onBeforeUnmount(() => ticket++)
  return { automatic, refresh }
}
