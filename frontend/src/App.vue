<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watchEffect } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import ConnectionIndicator from './components/ConnectionIndicator.vue'
import { useEventSocket } from './api/socket'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'
import NewConversationModal from './components/NewConversationModal.vue'
import { shouldOpenNewConversation } from './newConversationShortcut'
import { useNewConversationStore } from './stores/newConversation'

const socket = useEventSocket()
const layout = useLayoutStore()
const sessions = useSessionsStore()

const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting').length)
watchEffect(() => { document.title = documentTitle(waiting.value) })

const newConversation = useNewConversationStore()
const route = useRoute()
// The project in view: a project page, or the project of the open conversation.
function currentProjectId(): number | null {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
}
function onKey(event: KeyboardEvent) {
  if (newConversation.isOpen || !shouldOpenNewConversation(event)) return
  event.preventDefault()
  newConversation.open(currentProjectId())
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

onMounted(() => {
  void layout.restore()
  loadEverything().catch(() => {
    // The projects store keeps the error and the sidebar shows it.
  })
})
</script>

<template>
  <div class="flex h-full bg-bg text-sm leading-[1.45] text-fg">
    <AppSidebar />
    <main class="min-w-0 flex-1 overflow-y-auto">
      <RouterView />
    </main>
    <NewConversationModal v-if="newConversation.isOpen" />
    <ConnectionIndicator :status="socket.status.value" />
  </div>
</template>
