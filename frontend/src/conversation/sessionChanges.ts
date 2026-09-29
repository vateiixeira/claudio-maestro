import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, getSessionChanges } from '../api/http'
import { useConversationStore } from '../stores/conversation'
import type { ChangesGroup } from '../types/api'

/** Files changed by a session, reloaded at the end of each of its turns. */
export function useSessionChanges(sessionId: () => string) {
  const conversations = useConversationStore()
  const groups = ref<ChangesGroup[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const total = computed(() => {
    let added = 0
    let removed = 0
    for (const group of groups.value) {
      for (const file of group.files) {
        added += file.added ?? 0
        removed += file.removed ?? 0
      }
    }
    return { added, removed }
  })

  // Only the newest answer is applied; older requests are aborted.
  let generation = 0
  let controller: AbortController | null = null

  async function reload(): Promise<void> {
    const mine = ++generation
    controller?.abort()
    const ctrl = (controller = new AbortController())
    loading.value = true
    try {
      const result = await getSessionChanges(sessionId(), ctrl.signal)
      if (mine !== generation) return
      groups.value = result.repos
      error.value = null
    } catch (e) {
      if (mine === generation) error.value = errorMessage(e)
    } finally {
      if (mine === generation) loading.value = false
    }
  }

  watch(sessionId, () => {
    groups.value = []
    void reload()
  })
  watch(() => conversations.get(sessionId())?.lastResult, (result, before) => {
    if (result && result !== before) void reload()
  })
  onBeforeUnmount(() => {
    generation++
    controller?.abort()
  })
  void reload()

  return { groups, loading, error, total, reload }
}
