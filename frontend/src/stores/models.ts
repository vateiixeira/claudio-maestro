import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listModels } from '../api/http'
import type { ModelInfo } from '../types/api'

/** Models offered by the agent, fetched once and shared by every column. */
export const useModelsStore = defineStore('models', () => {
  const models = ref<ModelInfo[]>([])
  let loading: Promise<void> | null = null

  function ensure(): Promise<void> {
    loading ??= listModels()
      .then((list) => { models.value = Array.isArray(list) ? list : [] })
      .catch(() => { loading = null }) // tries again next time a column opens
    return loading
  }

  /** Fetches again (after the socket comes back, a `models.updated` may have been lost). */
  function reload(): Promise<void> {
    loading = null
    return ensure()
  }

  /** The backend learned the real list from the agent (`models.updated`). */
  function apply(list: unknown): void {
    if (!Array.isArray(list)) return
    models.value = list as ModelInfo[]
    loading ??= Promise.resolve()
  }

  return { models, ensure, apply, reload }
})
