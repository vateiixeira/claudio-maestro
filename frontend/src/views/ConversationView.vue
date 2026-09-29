<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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

const props = defineProps<{ id: string }>()

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
const wideScreen = useMediaQuery('(min-width: 1200px)')
const sideOpen = ref(readDetailsOpen())
const drawerOpen = ref(false)
function toggleDetails() {
  if (wideScreen.value) {
    sideOpen.value = !sideOpen.value
    writeDetailsOpen(sideOpen.value)
  } else {
    drawerOpen.value = !drawerOpen.value
  }
}
// "Ver alterações" in an edit card opens the panel (the drawer on narrow screens).
watch(() => changesPanel.sessionId === props.id && changesPanel.edit != null, (open) => {
  if (!open) return
  if (wideScreen.value) sideOpen.value = true
  else drawerOpen.value = true
}, { immediate: true })
</script>

<template>
  <div class="relative flex h-full min-w-0">
    <div class="flex min-w-0 grow flex-col">
      <div class="flex min-h-12 items-center gap-2 border-b border-line px-4">
        <nav data-test="breadcrumb" aria-label="Trilha" class="flex min-w-0 grow items-center gap-2 text-sm text-fg-muted">
          <RouterLink to="/sessions" class="shrink-0 font-mono text-xs tracking-[0.08em] uppercase no-underline text-fg-muted hover:text-fg">Conversas</RouterLink>
          <template v-if="project">
            <span aria-hidden="true">›</span>
            <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="flex shrink-0 items-center gap-1.5 no-underline text-fg-muted hover:text-fg">
              <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />{{ project.name }}
            </RouterLink>
          </template>
          <span aria-hidden="true">›</span>
          <span class="truncate text-fg">{{ title }}</span>
        </nav>
        <button
          v-if="!missing"
          type="button"
          data-test="toggle-details"
          :aria-pressed="wideScreen ? sideOpen : drawerOpen"
          aria-label="Mostrar ou esconder detalhes"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="toggleDetails"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="15" y1="4" x2="15" y2="20" /></svg>
        </button>
      </div>
      <div v-if="missing" data-test="conversation-missing" class="flex flex-col items-start gap-3 px-6 py-10">
        <h1 class="m-0 text-xl font-semibold">Conversa não encontrada</h1>
        <p class="m-0 text-fg-muted">Ela pode ter sido apagada fora do app.</p>
        <RouterLink to="/sessions" class="text-primary-soft">Ver todas as conversas</RouterLink>
      </div>
      <template v-else>
        <ConversationHeader :id="id" />
        <ConversationThread :id="id" @missing="missing = true" />
      </template>
    </div>
    <DetailsPanel v-if="!missing && wideScreen && sideOpen" :session-id="id" />
    <div v-if="!missing && !wideScreen && drawerOpen" data-test="details-drawer" class="absolute inset-y-0 right-0 z-30 flex shadow-2xl">
      <DetailsPanel :session-id="id" drawer @close="drawerOpen = false" />
    </div>
  </div>
</template>
