import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listModels } from '../api/http'
import type { AgentProvider, ModelInfo } from '../types/api'

/** Models offered by each agent provider, fetched once and shared by every column. */
export const useModelsStore = defineStore('models', () => {
  const models = ref<ModelInfo[]>([])
  const kimiModels = ref<ModelInfo[]>([])
  let loading: Promise<void> | null = null
  let kimiLoading: Promise<void> | null = null

  function ensure(): Promise<void> {
    loading ??= listModels()
      .then((list) => { models.value = Array.isArray(list) ? list : [] })
      .catch(() => { loading = null }) // tries again next time a column opens
    return loading
  }

  function ensureKimi(): Promise<void> {
    kimiLoading ??= listModels('kimi')
      .then((list) => { kimiModels.value = Array.isArray(list) ? list : [] })
      .catch(() => { kimiLoading = null })
    return kimiLoading
  }

  function ensureFor(provider: AgentProvider): Promise<void> {
    return provider === 'kimi' ? ensureKimi() : ensure()
  }

  function modelsFor(provider: AgentProvider): ModelInfo[] {
    return provider === 'kimi' ? kimiModels.value : models.value
  }

  /** Fetches again (after the socket comes back, a `models.updated` may have been lost). */
  function reload(): Promise<void> {
    loading = null
    kimiLoading = null
    return ensure()
  }

  /** The backend learned the real list from the agent (`models.updated`). */
  function apply(list: unknown, provider: AgentProvider = 'claude'): void {
    if (!Array.isArray(list)) return
    if (provider === 'kimi') {
      kimiModels.value = list as ModelInfo[]
      kimiLoading ??= Promise.resolve()
      return
    }
    models.value = list as ModelInfo[]
    loading ??= Promise.resolve()
  }

  return { models, kimiModels, ensure, ensureKimi, ensureFor, modelsFor, apply, reload }
})
