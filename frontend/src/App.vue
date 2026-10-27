<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch, watchEffect } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { AGENTS_NAVIGATION_KEY } from './agentsNavigation'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import { loadEverything } from './stores/realtime'
import { useLayoutStore } from './stores/layout'
import { isDiscarded } from './conversation/marks'
import { needsYou } from './conversation/needsYou'
import { documentTitle } from './documentTitle'
import { useSessionsStore } from './stores/sessions'
import NewConversationModal from './components/NewConversationModal.vue'
import UpdateModal from './components/updates/UpdateModal.vue'
import { shouldOpenNewConversation } from './newConversationShortcut'
import { nextNeedsYou } from './nextNeedsYou'
import { shouldGoToNextNeedsYou } from './nextNeedsYouShortcut'
import { useNewConversationStore } from './stores/newConversation'
import { useWorkStore } from './stores/work'
import { useUpdatesStore } from './stores/updates'

const layout = useLayoutStore()
const sessions = useSessionsStore()

const waiting = computed(() => sessions.all.filter((s) => s.display_state === 'waiting' && needsYou(s) && !isDiscarded(s)).length)
const route = useRoute()
const router = useRouter()
const compactViewport = ref(window.innerWidth < 1024)
const agentsMenuOpen = ref(false)
const agentsCompactNavigation = computed(() => ['agents', 'start', 'tasks', 'task', 'cto', 'projects'].includes(String(route.name)) && compactViewport.value)
let agentsMenuTrigger: HTMLElement | null = null
function closeAgentsMenu(restoreFocus = true) {
  agentsMenuOpen.value = false
  if (restoreFocus) void nextTick(() => agentsMenuTrigger?.isConnected && agentsMenuTrigger.focus())
}
function resizeAgentsNavigation() {
  compactViewport.value = window.innerWidth < 1024
  if (!compactViewport.value) closeAgentsMenu(false)
}
provide(AGENTS_NAVIGATION_KEY, {
  enabled: agentsCompactNavigation,
  open: agentsMenuOpen,
  toggle(trigger) {
    if (agentsMenuOpen.value) return closeAgentsMenu()
    agentsMenuTrigger = trigger
    agentsMenuOpen.value = true
    void nextTick(() => document.querySelector<HTMLElement>('.agents-mobile-sidebar a[href]')?.focus())
  },
})
watch(() => route.fullPath, () => closeAgentsMenu(false))
onMounted(() => window.addEventListener('resize', resizeAgentsNavigation))
onBeforeUnmount(() => window.removeEventListener('resize', resizeAgentsNavigation))
// The reader page (route meta `bare`) is the document alone: no shell, no live connection.
const ready = ref(false)
const bare = computed(() => route.meta.bare === true)
watchEffect(() => { if (ready.value && !bare.value) document.title = documentTitle(waiting.value) })

const newConversation = useNewConversationStore()
const updates = useUpdatesStore()
// The project in view: a project page, or the project of the open conversation.
function currentProjectId(): number | null {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'cto') return Number(route.query.projeto) || null
  if (route.name === 'tasks' || route.name === 'start') return Number(route.query.project ?? route.query.projeto) || null
  if (route.name === 'task') return useWorkStore().details[Number(route.params.id)]?.item.project_id ?? null
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
  if (route.name === 'cto') return useWorkStore().coordinators[Number(route.query.projeto)] ?? null
  if (route.name === 'project' && typeof route.query.sessao === 'string') return route.query.sessao
  return null
}
function onKey(event: KeyboardEvent) {
  if (agentsCompactNavigation.value && agentsMenuOpen.value) {
    if (event.key === 'Escape') { event.preventDefault(); closeAgentsMenu() }
    else if (event.key === 'Tab') {
      const focusable = [...document.querySelectorAll<HTMLElement>('.agents-mobile-sidebar a[href], .agents-mobile-sidebar button:not([disabled]), .agents-mobile-sidebar [tabindex="0"]')].filter((element) => element.getClientRects().length > 0)
      const first = focusable[0], last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    return
  }
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
    <button v-if="agentsCompactNavigation && agentsMenuOpen" type="button" class="agents-nav-backdrop" aria-label="Fechar navegação" @click="closeAgentsMenu()" />
    <AppSidebar :class="{ 'agents-mobile-sidebar': agentsCompactNavigation, 'is-open': agentsCompactNavigation && agentsMenuOpen }" :role="agentsCompactNavigation && agentsMenuOpen ? 'dialog' : undefined" :aria-modal="agentsCompactNavigation && agentsMenuOpen ? true : undefined" />
    <main :inert="agentsCompactNavigation && agentsMenuOpen" class="relative min-w-0 flex-1 overflow-y-auto bg-surface">
      <RouterView />
    </main>
    <NewConversationModal v-if="newConversation.isOpen" />
    <UpdateModal v-if="updates.modalOpen" />
  </div>
</template>

<style scoped>
.agents-mobile-sidebar { position:fixed; inset:0 auto 0 0; z-index:50; max-width:calc(100vw - 48px); box-shadow:12px 0 36px oklch(10% 0.005 250 / .2); }
.agents-mobile-sidebar:not(.is-open) { display:none; }
.agents-nav-backdrop { position:fixed; inset:0; z-index:40; border:0; background:oklch(10% 0.005 250 / .55); }
</style>
