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

  return { models, ensure }
})
