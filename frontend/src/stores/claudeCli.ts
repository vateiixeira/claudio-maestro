import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { ClaudeCliInfo } from '../types/api'

function isClaudeCliInfo(data: unknown): data is ClaudeCliInfo {
  if (typeof data !== 'object' || data === null) return false
  const value = data as Partial<ClaudeCliInfo>
  return (
    typeof value.in_use === 'object' && value.in_use !== null &&
    typeof value.can_update === 'boolean' &&
    typeof value.update_available === 'boolean'
  )
}

/** Which `claude` the app starts, and the "Atualizar o Claude" button of the model menus. */
export const useClaudeCliStore = defineStore('claudeCli', () => {
  const info = ref<ClaudeCliInfo | null>(null)
  const updating = ref(false)
  const result = ref<{ ok: boolean; message: string } | null>(null)
  // Bumped by every `claude_cli.state` event, so a slower GET started before it does not overwrite it.
  let applied = 0

  // Also busy when another tab started the update (the backend reports the job).
  const busy = computed(() => updating.value || info.value?.job?.state === 'running')

  async function load(): Promise<void> {
    const before = applied
    try {
      const loaded = await api.getClaudeCli()
      if (applied === before && isClaudeCliInfo(loaded)) info.value = loaded
    } catch {
      // Keeps the last info; the footer tries again next time the menu opens.
    }
  }

  function apply(data: unknown): void {
    if (!isClaudeCliInfo(data)) return
    applied += 1
    info.value = data
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

  return { info, busy, result, load, apply, update, clearResult }
})
