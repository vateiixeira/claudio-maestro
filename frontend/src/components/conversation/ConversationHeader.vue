<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import BranchLabel from '../git/BranchLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { errorMessage, openInEditor } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ id: string }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const git = useGitStore()

const listed = computed(() => sessions.find(props.id))
const conv = computed(() => conversations.get(props.id))
const title = computed(() => conv.value?.title ?? listed.value?.title ?? '')
const projectId = computed(() => listed.value?.project_id ?? conv.value?.projectId ?? null)
const project = computed(() => (projectId.value != null ? projects.byId(projectId.value) : undefined))
const repos = computed(() => (projectId.value != null ? git.reposFor(projectId.value) : []))
watch(projectId, (id) => { if (id != null) git.ensure(id) }, { immediate: true })
const isFinished = computed(() => listed.value?.display_state === 'finished')

const error = ref<string | null>(null)
const toggling = ref(false)
async function toggleFinished() {
  toggling.value = true
  error.value = null
  try {
    await sessions.setFinished(props.id, !isFinished.value)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    toggling.value = false
  }
}

// Inline rename: Enter saves, Esc cancels.
const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)
async function startRename() {
  menuOpen.value = false
  draft.value = title.value
  error.value = null
  editing.value = true
  await nextTick()
  input.value?.select()
}
async function saveRename() {
  const value = draft.value.trim()
  if (!value) {
    error.value = 'O título não pode ficar vazio.'
    return
  }
  try {
    await sessions.rename(props.id, value)
    if (conv.value) conv.value.title = value
    editing.value = false
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

const menuOpen = ref(false)
const menuWrap = ref<HTMLElement | null>(null)
const menuButton = ref<HTMLButtonElement | null>(null)
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  menuOpen.value = false
  menuButton.value?.focus()
}
function onDocumentPointerdown(event: Event) {
  if (menuWrap.value && event.target instanceof Node && menuWrap.value.contains(event.target)) return
  menuOpen.value = false
}
function removeMenuListeners() {
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('pointerdown', onDocumentPointerdown)
}
// While the menu is open, Esc anywhere and a click outside close it.
watch(menuOpen, (open) => {
  removeMenuListeners()
  if (!open) return
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('pointerdown', onDocumentPointerdown)
})
onBeforeUnmount(removeMenuListeners)
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null
onBeforeUnmount(() => { if (copiedTimer) clearTimeout(copiedTimer) })
async function copyId() {
  menuOpen.value = false
  try {
    await navigator.clipboard.writeText(props.id)
    copied.value = true
    copiedTimer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    error.value = 'Não foi possível copiar o ID.'
  }
}
async function openProject() {
  menuOpen.value = false
  if (!project.value) return
  try {
    await openInEditor(project.value.path)
  } catch (e) {
    error.value = errorMessage(e)
  }
}
</script>

<template>
  <header class="mx-auto flex w-full max-w-[760px] flex-col gap-2 px-4 pt-5 pb-3">
    <div class="flex items-start gap-3">
      <DisplayStateIcon v-if="listed" :display="listed.display_state" :size="16" class="mt-2" />
      <input
        v-if="editing"
        ref="input"
        v-model="draft"
        data-test="title-input"
        aria-label="Título da conversa"
        maxlength="200"
        class="h-10 min-w-0 grow rounded-md border border-line-strong bg-bg px-2.5 text-xl font-semibold text-fg outline-none focus:border-primary"
        @keydown.enter.prevent="saveRename"
        @keydown.esc.prevent="editing = false"
      />
      <h1 v-else class="m-0 min-w-0 grow text-2xl font-semibold tracking-tight">
        <button
          type="button"
          data-test="conversation-title"
          title="Clique para renomear"
          class="max-w-full text-left hover:text-primary-soft focus-visible:outline-2 focus-visible:outline-primary"
          @click="startRename"
        >{{ title }}</button>
      </h1>
      <button
        v-if="listed"
        type="button"
        data-test="toggle-finished"
        class="h-9 shrink-0 rounded-md border border-line-strong px-3 text-sm font-medium hover:bg-card disabled:opacity-40"
        :class="isFinished ? 'text-primary-soft' : 'text-fg'"
        :disabled="toggling"
        @click="toggleFinished"
      >{{ isFinished ? 'Reabrir' : 'Finalizar' }}</button>
      <div ref="menuWrap" class="relative shrink-0">
        <button
          ref="menuButton"
          type="button"
          data-test="header-menu"
          aria-label="Mais ações"
          :aria-expanded="menuOpen"
          class="flex size-9 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="menuOpen = !menuOpen"
        >⋯</button>
        <div
          v-if="menuOpen"
          role="menu"
          class="absolute right-0 z-20 mt-1 flex w-56 flex-col rounded-lg border border-line-strong bg-elevated py-1 shadow-lg"
        >
          <button type="button" role="menuitem" data-test="menu-rename" class="px-3 py-2 text-left text-sm hover:bg-card" @click="startRename">Renomear</button>
          <button type="button" role="menuitem" data-test="menu-editor" class="px-3 py-2 text-left text-sm hover:bg-card" :disabled="!project" @click="openProject">Abrir projeto no editor</button>
          <button type="button" role="menuitem" data-test="menu-copy-id" class="px-3 py-2 text-left text-sm hover:bg-card" @click="copyId">Copiar ID da sessão</button>
        </div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-1.5 pl-7">
      <span v-if="project" class="flex items-center gap-1.5 rounded-full border border-line-strong bg-card px-2.5 py-[3px] text-xs">
        <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />{{ project.name }}
      </span>
      <span v-for="repo in repos" :key="repo.path" class="flex items-center rounded-full border border-line-strong bg-card px-2.5 py-[3px]">
        <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
      </span>
      <span v-if="copied" role="status" class="text-xs text-primary-soft">ID copiado</span>
    </div>
    <p v-if="error" data-test="header-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p
      v-if="conv?.externalActivity"
      data-test="external-activity"
      role="status"
      class="m-0 rounded-md border border-secondary/40 bg-secondary/10 px-3 py-2 text-xs text-secondary-soft"
    >Esta sessão foi modificada fora do app no último minuto. Usar a mesma sessão no CLI e aqui ao mesmo tempo pode embaralhar o histórico.</p>
  </header>
</template>
