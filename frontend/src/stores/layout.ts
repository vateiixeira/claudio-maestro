import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/http'

export const DEFAULT_FINISHED_AFTER_DAYS = 3

/**
 * Preferences needed by the shell. A failed startup read is tried again on reconnect.
 */
export const useLayoutStore = defineStore('layout', () => {
  const restored = ref(false)
  const loadedFromServer = ref(false)
  const finishedAfterDays = ref(DEFAULT_FINISHED_AFTER_DAYS)
  const codexEnabled = ref(false)

  // Startup and a reconnect can ask at the same time: share the read in flight.
  let inFlight: Promise<void> | null = null
  function restore(): Promise<void> {
    if (!inFlight) inFlight = doRestore().finally(() => { inFlight = null })
    return inFlight
  }

  async function doRestore(): Promise<void> {
    try {
      const state = await api.getAppState()
      const preferences = state?.preferences as Record<string, unknown> | undefined
      const days = preferences?.finished_after_days
      if (typeof days === 'number' && Number.isFinite(days) && days > 0) finishedAfterDays.value = days
      codexEnabled.value = preferences?.codex_enabled === true
      loadedFromServer.value = true
    } catch {
      // Defaults stay; the reconnect tries again.
    } finally {
      restored.value = true
    }
  }

  return { restored, loadedFromServer, finishedAfterDays, codexEnabled, restore }
})
