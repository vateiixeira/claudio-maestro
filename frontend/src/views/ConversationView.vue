<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ConversationHeader from '../components/conversation/ConversationHeader.vue'
import ConversationThread from '../components/conversation/ConversationThread.vue'
import DetailsPanel from '../components/details/DetailsPanel.vue'
import { readDetailsOpen, writeDetailsOpen } from '../detailsPanelPref'
import { useMediaQuery } from '../useMediaQuery'
import { useChangesPanelStore } from '../stores/changesPanel'
import { useConversationStore } from '../stores/conversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

// `embedded`: shown beside the project list. `projectId` is the project that list belongs to: "Fechar"
// goes back to it, even if `?sessao=` points at a conversation of another project or one that is gone.
const props = defineProps<{ id: string; embedded?: boolean; projectId?: number }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const changesPanel = useChangesPanelStore()

const title = computed(() => conversations.get(props.id)?.title ?? sessions.find(props.id)?.title ?? '')
const project = computed(() => {
  const id = sessions.find(props.id)?.project_id ?? conversations.get(props.id)?.projectId
  return id != null ? projects.byId(id) : undefined
})

const missing = ref(false)
watch(() => props.id, () => { missing.value = false })

// Wide screens: a side panel whose open state is remembered. Narrow: a drawer, closed at first.
// Embedded, the column is narrow: always the drawer.
const wideScreen = useMediaQuery('(min-width: 1200px)')
const sidePanel = computed(() => wideScreen.value && !props.embedded)
const closeProjectId = computed(() => props.projectId ?? project.value?.id)
const sideOpen = ref(readDetailsOpen())
const drawerOpen = ref(false)
const detailsOpen = computed(() => (sidePanel.value ? sideOpen.value : drawerOpen.value))
function toggleDetails() {
  if (sidePanel.value) {
    sideOpen.value = !sideOpen.value
    writeDetailsOpen(sideOpen.value)
  } else {
    drawerOpen.value = !drawerOpen.value
  }
}
// The drawer takes focus when it opens; Esc closes it and hands focus back to the toggle.
// It listens on `window`, after every handler on the document or below it: an Esc that a menu,
// dialog, rename or search already handled arrives with `defaultPrevented` set, and only the
// topmost layer closes. Layers that consume Esc must call `preventDefault()`.
const toggleButton = ref<HTMLButtonElement | null>(null)
const drawer = ref<HTMLElement | null>(null)
function closeDrawer() {
  drawerOpen.value = false
  toggleButton.value?.focus()
}
function onDrawerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault()
  closeDrawer()
}
watch(drawerOpen, async (open) => {
  window.removeEventListener('keydown', onDrawerKeydown)
  if (!open) return
  window.addEventListener('keydown', onDrawerKeydown)
  await nextTick()
  drawer.value?.querySelector<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')?.focus()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onDrawerKeydown))

// "Ver alterações" in an edit card opens the panel (the drawer on narrow screens).
watch(() => changesPanel.sessionId === props.id && changesPanel.edit != null, (open) => {
  if (!open) return
  if (sidePanel.value) sideOpen.value = true
  else drawerOpen.value = true
}, { immediate: true })
</script>

<template>
  <div class="relative flex h-full min-w-0">
    <div class="flex min-w-0 grow flex-col">
      <div v-if="embedded" data-test="embedded-bar" class="flex min-h-12 items-center gap-1 border-b border-line pr-2 pl-4">
        <span data-test="embedded-title" :title="title" class="min-w-0 grow truncate text-sm font-medium text-fg">{{ title }}</span>
        <button
          v-if="!missing"
          ref="toggleButton"
          type="button"
          data-test="toggle-details"
          :aria-pressed="detailsOpen"
          aria-label="Mostrar ou esconder detalhes"
          title="Mostrar ou esconder detalhes"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="toggleDetails"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" /></svg>
        </button>
        <RouterLink
          :to="{ name: 'session', params: { id } }"
          data-test="embedded-fullscreen"
          aria-label="Abrir em tela cheia"
          title="Abrir em tela cheia"
          class="flex size-8 shrink-0 items-center justify-center rounded-md text-fg-muted no-underline hover:bg-card hover:text-fg"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></svg>
        </RouterLink>
        <RouterLink
          v-if="closeProjectId != null"
          :to="{ name: 'project', params: { id: closeProjectId } }"
          data-test="embedded-close"
          aria-label="Fechar conversa"
          title="Fechar conversa"
          class="flex size-8 shrink-0 items-center justify-center rounded-md text-fg-muted no-underline hover:bg-card hover:text-fg"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </RouterLink>
      </div>
      <!-- Not embedded and gone: no header to carry the path, so a bare one. -->
      <nav v-else-if="missing" data-test="breadcrumb" aria-label="Trilha" class="flex min-h-14 items-center border-b border-line px-4 text-sm text-fg-muted">
        <RouterLink to="/sessions" class="no-underline text-fg-muted hover:text-fg">Conversas</RouterLink>
      </nav>
      <div v-if="missing" data-test="conversation-missing" class="flex flex-col items-start gap-3 px-6 py-10">
        <h1 class="m-0 text-xl font-semibold">Conversa não encontrada</h1>
        <p class="m-0 text-fg-muted">Ela pode ter sido apagada fora do app.</p>
        <RouterLink to="/sessions" class="text-info-soft">Ver todas as conversas</RouterLink>
      </div>
      <template v-else>
        <!-- Keyed by id: a rename in progress or the scroll position must not carry over to another conversation. -->
        <ConversationHeader :key="id" :id="id" :details-open="detailsOpen" :show-path="!embedded">
          <template v-if="!embedded" #details-toggle>
            <button
              ref="toggleButton"
              type="button"
              data-test="toggle-details"
              :aria-pressed="detailsOpen"
              aria-label="Mostrar ou esconder detalhes"
              title="Mostrar ou esconder detalhes"
              class="flex size-8 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
              @click="toggleDetails"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" /></svg>
            </button>
          </template>
        </ConversationHeader>
        <ConversationThread :key="id" :id="id" @missing="missing = true" />
      </template>
    </div>
    <DetailsPanel v-if="!missing && sidePanel && sideOpen" :session-id="id" />
    <div v-if="!missing && !sidePanel && drawerOpen" ref="drawer" data-test="details-drawer" class="absolute inset-y-0 right-0 z-30 flex max-w-full shadow-2xl">
      <DetailsPanel :session-id="id" drawer @close="closeDrawer" />
    </div>
  </div>
</template>
