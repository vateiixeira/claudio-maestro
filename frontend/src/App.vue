<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'
import { needsYou } from './conversation/needsYou'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'
import NewConversationModal from './components/NewConversationModal.vue'
import UpdateModal from './components/updates/UpdateModal.vue'
import { shouldOpenNewConversation } from './newConversationShortcut'
import { nextNeedsYou } from './nextNeedsYou'
import { shouldGoToNextNeedsYou } from './nextNeedsYouShortcut'
import { useNewConversationStore } from './stores/newConversation'
import { useUpdatesStore } from './stores/updates'

const layout = useLayoutStore()
const sessions = useSessionsStore()

const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting' && needsYou(s)).length)
const route = useRoute()
const router = useRouter()
// The reader page (route meta `bare`) is the document alone: no shell, no live connection.
const ready = ref(false)
const bare = computed(() => route.meta.bare === true)
watchEffect(() => { if (ready.value && !bare.value) document.title = documentTitle(waiting.value) })

const newConversation = useNewConversationStore()
const updates = useUpdatesStore()
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
// The conversation in view, full screen or beside its project (`?sessao=`): the "next" one is never it.
function currentSessionId(): string | null {
  if (route.name === 'session') return String(route.params.id)
  if (route.name === 'project' && typeof route.query.sessao === 'string') return route.query.sessao
  return null
}
function onKey(event: KeyboardEvent) {
  if (bare.value) return
  if (newConversation.isOpen) return
  if (shouldOpenNewConversation(event)) {
    event.preventDefault()
    newConversation.open(currentProjectId(), currentGroupId())
    return
  }
  if (!shouldGoToNextNeedsYou(event)) return
  const next = nextNeedsYou(sessions.all, currentSessionId())
  if (!next) return
  event.preventDefault()
  void router.push({ name: 'session', params: { id: next.session_id } })
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

onMounted(async () => {
  // Decides after the first route is known, so the reader tab never starts the shell.
  await router.isReady()
  ready.value = true
  if (bare.value) return
  void layout.restore()
  loadEverything().catch(() => {
    // The projects store keeps the error and the sidebar shows it.
  })
})
</script>

<template>
  <div v-if="ready && bare" class="h-full overflow-y-auto bg-surface text-sm leading-[1.45] text-fg">
    <RouterView />
  </div>
  <div v-else-if="ready" class="flex h-full overflow-hidden bg-bg text-sm leading-[1.45] text-fg">
    <AppSidebar />
    <main class="relative min-w-0 flex-1 overflow-y-auto bg-surface">
      <RouterView />
    </main>
    <NewConversationModal v-if="newConversation.isOpen" />
    <UpdateModal v-if="updates.modalOpen" />
  </div>
</template>
