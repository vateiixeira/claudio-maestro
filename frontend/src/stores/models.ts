import { defineStore } from 'pinia'
import { computed, reactive } from 'vue'
import { listModels } from '../api/http'
import type { AgentProvider, ModelInfo } from '../types/api'

/** Models offered by each agent provider, fetched once and shared by every column. */
export const useModelsStore = defineStore('models', () => {
  const catalog = reactive<Record<AgentProvider, ModelInfo[]>>({ claude: [], kimi: [], codex: [] })
  const requests = new Map<AgentProvider, Promise<void>>()
  const requested = new Set<AgentProvider>()

  const models = computed(() => catalog.claude)
  const kimiModels = computed(() => catalog.kimi)
  const codexModels = computed(() => catalog.codex)

  function ensureFor(provider: AgentProvider): Promise<void> {
    requested.add(provider)
    const current = requests.get(provider)
    if (current) return current
    const request = listModels(provider)
      .then((list) => {
        if (requests.get(provider) === request) catalog[provider] = Array.isArray(list) ? list : []
      })
      .catch(() => {
        if (requests.get(provider) === request) requests.delete(provider)
      })
    requests.set(provider, request)
    return request
  }

  const ensure = () => ensureFor('claude')
  const ensureKimi = () => ensureFor('kimi')
  const modelsFor = (provider: AgentProvider) => catalog[provider]

  function reloadFor(provider: AgentProvider): Promise<void> {
    requests.delete(provider)
    return ensureFor(provider)
  }

  /** Only refresh providers already used here when a socket reconnects. */
  async function reload(): Promise<void> {
    await Promise.all([...new Set<AgentProvider>(['claude', ...requested])].map(reloadFor))
  }

  /** The backend learned the real list from the agent (`models.updated`). */
  function apply(list: unknown, provider: AgentProvider = 'claude'): void {
    if (!Object.hasOwn(catalog, provider) || !Array.isArray(list)) return
    requested.add(provider)
    catalog[provider] = list as ModelInfo[]
    requests.set(provider, Promise.resolve())
  }

  return { models, kimiModels, codexModels, ensure, ensureKimi, ensureFor, modelsFor, apply, reload, reloadFor }
})
