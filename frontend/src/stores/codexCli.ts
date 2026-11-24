import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, getCodexCli, refreshCodexCli, updateCodexCli } from '../api/http'
import type { CodexCliInfo } from '../types/api'
import { useModelsStore } from './models'

export const useCodexCliStore = defineStore('codexCli', () => {
  const info = ref<CodexCliInfo | null>(null)
  const busy = ref<'refresh' | 'update' | null>(null)
  const loading = ref(false)
  const readError = ref<string | null>(null)
  const result = ref<{ ok: boolean; message: string } | null>(null)
  const models = useModelsStore()
  let revision = 0
  let checkedAt = -Infinity

  async function load(maxAgeMs = 0): Promise<void> {
    const now = Date.now()
    if (busy.value || loading.value || now - checkedAt < maxAgeMs) return
    const before = revision
    checkedAt = now
    loading.value = true
    readError.value = null
    try {
      const loaded = await getCodexCli()
      if (before === revision) info.value = loaded
    } catch (error) {
      if (before === revision) readError.value = errorMessage(error)
    } finally {
      loading.value = false
    }
  }

  async function run(action: NonNullable<typeof busy.value>): Promise<void> {
    if (busy.value) return
    revision++
    checkedAt = Date.now()
    busy.value = action
    readError.value = null
    result.value = null
    try {
      if (action === 'update') {
        const outcome = await updateCodexCli()
        info.value = outcome
        result.value = { ok: outcome.ok, message: outcome.message }
      } else {
        const outcome = await refreshCodexCli()
        info.value = outcome
        result.value = outcome.models_refreshed
          ? { ok: true, message: 'Catálogo de modelos atualizado.' }
          : { ok: false, message: outcome.error ?? 'Não foi possível atualizar o catálogo de modelos.' }
      }
      if (info.value.models_refreshed) await models.reloadFor('codex')
    } catch (error) {
      result.value = { ok: false, message: errorMessage(error) }
    } finally {
      busy.value = null
    }
  }

  return { info, busy, loading, readError, result, load, run }
})
