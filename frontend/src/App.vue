<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watchEffect } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'
import { needsYou } from './conversation/needsYou'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'
import NewConversationModal from './components/NewConversationModal.vue'
import { shouldOpenNewConversation } from './newConversationShortcut'
import { useNewConversationStore } from './stores/newConversation'

const layout = useLayoutStore()
const sessions = useSessionsStore()

const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting' && needsYou(s)).length)
watchEffect(() => { document.title = documentTitle(waiting.value) })

const newConversation = useNewConversationStore()
const route = useRoute()
// The project in view: a project page, or the project of the open conversation.
function currentProjectId(): number | null {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
}
// The group of the open conversation, so a new one starts next to it.
// `null` = the conversation has no group; `undefined` = no conversation open, so no preference.
function currentGroupId(): number | null | undefined {
  if (route.name !== 'session') return undefined
  const session = sessions.find(String(route.params.id))
  return session ? (session.group_id ?? null) : undefined
}
function onKey(event: KeyboardEvent) {
  if (newConversation.isOpen || !shouldOpenNewConversation(event)) return
  event.preventDefault()
  newConversation.open(currentProjectId(), currentGroupId())
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
    <main class="relative min-w-0 flex-1 overflow-y-auto bg-surface">
      <RouterView />
    </main>
    <NewConversationModal v-if="newConversation.isOpen" />
  </div>
</template>
