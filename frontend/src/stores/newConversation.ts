import { defineStore } from 'pinia'
import { ref } from 'vue'

/** Whether the "Nova conversa" modal is open, and the project and group it should start on. */
export const useNewConversationStore = defineStore('newConversation', () => {
  const isOpen = ref(false)
  const presetProjectId = ref<number | null>(null)
  const presetGroupId = ref<number | null>(null)

  function open(projectId: number | null = null, groupId: number | null = null): void {
    presetProjectId.value = projectId
    presetGroupId.value = groupId
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  return { isOpen, presetProjectId, presetGroupId, open, close }
})
