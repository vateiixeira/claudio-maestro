import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { UsageLimit, UsageSnapshot } from '../types/api'

function isUsageSnapshot(data: unknown): data is UsageSnapshot {
  if (typeof data !== 'object' || data === null) return false
  const value = data as Partial<UsageSnapshot>
  return typeof value.enabled === 'boolean' && Array.isArray(value.limits)
}

/** Subscription usage (session and week), read by the backend every 3 min and after turns. */
export const useUsageStore = defineStore('usage', () => {
  const snapshot = ref<UsageSnapshot | null>(null)
  // Bumped by every event, so a slower GET started before it does not overwrite it.
  let applied = 0

  const find = (kind: UsageLimit['kind']) => snapshot.value?.limits.find((l) => l.kind === kind) ?? null
  const session = computed(() => find('session'))
  const weekly = computed(() => find('weekly_all'))
  const scoped = computed(() => snapshot.value?.limits.filter((l) => l.kind === 'weekly_scoped') ?? [])

  async function load(): Promise<void> {
    const before = applied
    const result = await api.getUsage()
    if (applied === before && isUsageSnapshot(result)) snapshot.value = result
  }

  function apply(data: unknown): void {
    if (!isUsageSnapshot(data)) return
    applied += 1
    snapshot.value = data
  }

  return { snapshot, session, weekly, scoped, load, apply }
})
