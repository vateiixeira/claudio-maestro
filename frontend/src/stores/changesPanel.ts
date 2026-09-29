import { defineStore } from 'pinia'
import { ref, type ComputedRef, type InjectionKey } from 'vue'
import type { ToolItem } from '../types/conversation'

/** Session id of the column an edit card lives in. */
export const SESSION_ID_KEY: InjectionKey<ComputedRef<string>> = Symbol('sessionId')

/** The changes panel: at most one open in the whole workspace. */
export const useChangesPanelStore = defineStore('changesPanel', () => {
  const sessionId = ref<string | null>(null)
  const edit = ref<ToolItem | null>(null)

  function open(id: string, item: ToolItem): void {
    sessionId.value = id
    edit.value = item
  }

  function close(): void {
    sessionId.value = null
    edit.value = null
  }

  return { sessionId, edit, open, close }
})
