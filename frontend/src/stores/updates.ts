import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/http'
import type { UpdateState } from '../types/api'

const DISMISSED_KEY = 'maestro:update-dismissed'

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

function isUpdateState(data: unknown): data is UpdateState {
  if (typeof data !== 'object' || data === null) return false
  const value = data as Partial<UpdateState>
  return typeof value.current === 'string' && typeof value.available === 'boolean' && typeof value.enabled === 'boolean'
}

/** Installed version and whether a newer release exists (the backend checks GitHub once a day). */
export const useUpdatesStore = defineStore('updates', () => {
  const state = ref<UpdateState | null>(null)
  const dismissed = ref<string | null>(readDismissed())
  const modalOpen = ref(false)
  // Bumped by every event, so a slower GET started before it does not overwrite it.
  let applied = 0

  const showNotice = computed(() => {
    const s = state.value
    return !!s && s.enabled && s.available && !!s.latest && s.latest.version !== dismissed.value
  })

  async function load(): Promise<void> {
    const before = applied
    const result = await api.getUpdates()
    if (applied === before) state.value = result
  }

  function apply(data: unknown): void {
    if (!isUpdateState(data)) return
    applied += 1
    state.value = data
  }

  function dismiss(): void {
    const version = state.value?.latest?.version
    if (!version) return
    dismissed.value = version
    try {
      localStorage.setItem(DISMISSED_KEY, version)
    } catch {
      // Blocked storage: the notice stays hidden only in this tab.
    }
    modalOpen.value = false
  }

  function openModal(): void {
    if (state.value?.latest) modalOpen.value = true
  }

  function closeModal(): void {
    modalOpen.value = false
  }

  return { state, showNotice, modalOpen, load, apply, dismiss, openModal, closeModal }
})
