import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Whether the "Nova conversa" modal is open, and the project and group it should start on.
 * `presetGroupId`: `undefined` = no preference (the saved draft applies), `null` = no group.
 */
export const useNewConversationStore = defineStore('newConversation', () => {
  const isOpen = ref(false)
  const presetProjectId = ref<number | null>(null)
  const presetGroupId = ref<number | null | undefined>(undefined)

  function open(projectId: number | null = null, groupId?: number | null): void {
    presetProjectId.value = projectId
    presetGroupId.value = groupId
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  return { isOpen, presetProjectId, presetGroupId, open, close }
})
