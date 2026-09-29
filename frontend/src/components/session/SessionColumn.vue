<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage } from '../../api/http'
import SessionStateIcon from '../SessionStateIcon.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { repoLabel, useGitStore } from '../../stores/git'
import ConversationThread from '../conversation/ConversationThread.vue'
import { deriveDisplay, displayStateLabels } from '../../sessionState'
import { useConversationStore } from '../../stores/conversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'

const props = withDefaults(defineProps<{ id: string; visible?: boolean }>(), { visible: true })
const emit = defineEmits<{ close: []; missing: [] }>()

const conversations = useConversationStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const listed = computed(() => sessions.find(props.id))
const isFinished = computed(() => listed.value?.display_state === 'finished')
// Label the user sees: the display state, except errors and pending decisions.
const stateLabel = computed(() => {
  const c = conv.value
  if (!c) return ''
  if (c.state === 'error') return 'Erro'
  if (c.state === 'awaiting_decision') return 'Pede sua decisão'
  const shown = deriveDisplay(c.state, listed.value?.finished ?? false, listed.value?.display_state)
  return displayStateLabels[shown.display_state]
})

const headerError = ref<string | null>(null)
const toggling = ref(false)
async function toggleFinished() {
  toggling.value = true
  headerError.value = null
  try {
    await sessions.setFinished(props.id, !isFinished.value)
  } catch (e) {
    headerError.value = errorMessage(e)
  } finally {
    toggling.value = false
  }
}

// Inline rename: Enter saves, Esc cancels.
const editing = ref(false)
const titleDraft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)
async function startRename() {
  titleDraft.value = conv.value?.title ?? ''
  headerError.value = null
  editing.value = true
  await nextTick()
  titleInput.value?.select()
}
function cancelRename() {
  editing.value = false
  headerError.value = null
}
async function saveRename() {
  const title = titleDraft.value.trim()
  if (!title) {
    headerError.value = 'O título não pode ficar vazio.'
    return
  }
  try {
    await sessions.rename(props.id, title)
    if (conv.value) conv.value.title = title
    editing.value = false
    headerError.value = null
  } catch (e) {
    headerError.value = errorMessage(e)
  }
}

const conv = computed(() => conversations.get(props.id))
const project = computed(() => (conv.value?.projectId != null ? projects.byId(conv.value.projectId) : undefined))
const git = useGitStore()
const repos = computed(() => (project.value ? git.reposFor(project.value.id) : []))
watch(() => project.value?.id, (id) => { if (id != null) git.ensure(id) }, { immediate: true })
</script>

<template>
  <section :aria-label="conv ? `Sessão: ${conv.title}` : 'Sessão'" class="flex h-full min-w-0 flex-col">
    <template v-if="conv">
      <header class="flex flex-col gap-2 border-b border-line px-4 pt-4 pb-3">
        <div class="flex items-center gap-2">
          <RouterLink
            v-if="project"
            :to="{ name: 'project', params: { id: project.id } }"
            class="flex min-w-0 grow items-center gap-2 text-xs text-fg-muted no-underline hover:text-fg"
          >
            <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
            <span class="truncate">{{ project.name }}</span>
          </RouterLink>
          <span v-else class="grow" />
          <span
            data-test="session-state"
            role="status"
            aria-live="polite"
            class="flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-xs font-semibold"
            :class="{
              'border-primary/40 bg-primary/10 text-primary-soft': conv.state === 'running' || conv.state === 'connecting',
              'border-secondary/40 bg-secondary/10 text-secondary': conv.state === 'awaiting_decision' || conv.state === 'error',
              'border-line-strong bg-card text-fg-muted': conv.state === 'idle' || conv.state === 'closed',
            }"
          >
            <SessionStateIcon :state="conv.state" />
            {{ stateLabel }}
          </span>
          <button
            type="button"
            aria-label="Fechar coluna"
            title="Fechar coluna (a sessão continua)"
            class="flex size-8 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
            @click="emit('close')"
          >
            <svg viewBox="0 0 16 16" class="size-4" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
        <div class="flex items-start gap-2">
          <input
            v-if="editing"
            ref="titleInput"
            v-model="titleDraft"
            data-test="title-input"
            aria-label="Título da sessão"
            maxlength="200"
            class="h-9 min-w-0 grow rounded-md border border-line-strong bg-bg px-2.5 text-base font-semibold text-fg outline-none focus:border-primary"
            @keydown.enter.prevent="saveRename"
            @keydown.esc.prevent="cancelRename"
          />
          <h2 v-else class="m-0 min-w-0 grow text-lg font-semibold">
            <button
              type="button"
              data-test="session-title"
              title="Clique para renomear"
              class="max-w-full truncate rounded-md text-left hover:text-primary-soft focus-visible:outline-2 focus-visible:outline-primary"
              @click="startRename"
            >{{ conv.title }}</button>
          </h2>
          <button
            v-if="!editing"
            type="button"
            data-test="rename-session"
            class="h-9 shrink-0 rounded-md px-2.5 text-sm text-fg-muted hover:bg-card hover:text-fg"
            @click="startRename"
          >
            Renomear
          </button>
          <button
            v-if="listed"
            type="button"
            data-test="toggle-finished"
            class="h-9 shrink-0 rounded-md border border-line-strong px-2.5 text-sm font-medium hover:bg-card disabled:opacity-40"
            :class="isFinished ? 'text-primary-soft' : 'text-fg'"
            :disabled="toggling"
            @click="toggleFinished"
          >{{ isFinished ? 'Reabrir' : 'Finalizar' }}</button>
        </div>
        <div v-if="repos.length > 0" role="group" aria-label="Branches" class="flex flex-wrap gap-1.5">
          <span
            v-for="repo in repos"
            :key="repo.path"
            data-test="branch-chip"
            class="flex min-w-0 max-w-full items-center rounded-full border border-line-strong bg-card px-2.5 py-[3px]"
          >
            <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
          </span>
        </div>
        <span
          v-else-if="project && git.isLoaded(project.id)"
          data-test="no-git"
          class="text-xs text-fg-muted"
        >sem repositório git</span>
        <p v-if="headerError" role="alert" class="m-0 text-sm text-secondary-soft">{{ headerError }}</p>
        <p
          v-if="conv.externalActivity"
          data-test="external-activity"
          role="status"
          class="m-0 rounded-md border border-secondary/40 bg-secondary/10 px-3 py-2 text-xs text-secondary-soft"
        >
          Esta sessão foi modificada fora do app no último minuto. Usar a mesma sessão no CLI e aqui ao mesmo tempo pode embaralhar o histórico.
        </p>
      </header>
    </template>
    <ConversationThread :id="id" :visible="visible" @missing="emit('missing')">
      <template #load-error-actions>
        <button
          type="button"
          aria-label="Fechar coluna"
          class="min-h-9 rounded-md border border-line-strong px-3 text-sm text-fg hover:bg-card"
          @click="emit('close')"
        >
          Fechar coluna
        </button>
      </template>
    </ConversationThread>
  </section>
</template>
