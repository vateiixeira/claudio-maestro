import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { ClaudeCliInfo } from '../types/api'

/** Which `claude` the app starts, and the "Atualizar o Claude" button of the model menus. */
export const useClaudeCliStore = defineStore('claudeCli', () => {
  const info = ref<ClaudeCliInfo | null>(null)
  const updating = ref(false)
  const result = ref<{ ok: boolean; message: string } | null>(null)

  // Also busy when another tab started the update (the backend reports the job).
  const busy = computed(() => updating.value || info.value?.job?.state === 'running')

  async function load(): Promise<void> {
    try {
      info.value = await api.getClaudeCli()
    } catch {
      // Keeps the last info; the footer tries again next time the menu opens.
    }
  }

  async function update(): Promise<void> {
    if (busy.value) return
    updating.value = true
    result.value = null
    try {
      const outcome = await api.updateClaudeCli()
      result.value = { ok: outcome.ok, message: outcome.message }
    } catch (error) {
      result.value = { ok: false, message: api.errorMessage(error) }
    } finally {
      updating.value = false
    }
    await load()
  }

  function clearResult(): void {
    result.value = null
  }

  return { info, busy, result, load, update, clearResult }
})
