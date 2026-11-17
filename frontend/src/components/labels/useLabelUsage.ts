import { computed, type ComputedRef } from 'vue'
import { useSessionsStore } from '../../stores/sessions'

/**
 * How many conversations of the store carry each label (every project counts). Until the
 * conversations are loaded (`ready` false) or one of them failed to load a count of zero means "unknown", so `countText` is empty
 * and callers must not treat a label as unused.
 */
export function useLabelUsage(): { ready: ComputedRef<boolean>; count(id: number): number; countText(id: number): string } {
  const sessions = useSessionsStore()

  const usage = computed(() => {
    const counts: Record<number, number> = {}
    for (const list of Object.values(sessions.byProject)) {
      for (const session of list) for (const id of session.label_ids ?? []) counts[id] = (counts[id] ?? 0) + 1
    }
    return counts
  })

  const ready = computed(() => sessions.complete)
  const count = (id: number): number => usage.value[id] ?? 0
  const countText = (id: number): string => {
    if (!ready.value) return ''
    const total = count(id)
    if (total === 0) return 'sem uso'
    return `${total} ${total === 1 ? 'conversa' : 'conversas'}`
  }

  return { ready, count, countText }
}
