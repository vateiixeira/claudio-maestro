import { defineStore } from 'pinia'
import { ref } from 'vue'

/** Whether the "Nova conversa" modal is open, and the project it should start on. */
export const useNewConversationStore = defineStore('newConversation', () => {
  const isOpen = ref(false)
  const presetProjectId = ref<number | null>(null)

  function open(projectId: number | null = null): void {
    presetProjectId.value = projectId
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  return { isOpen, presetProjectId, open, close }
})
