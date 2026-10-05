<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import BranchLabel from '../git/BranchLabel.vue'
import WorktreeLabel from '../git/WorktreeLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import MarkIcon from '../MarkIcon.vue'
import MarkPopover from '../marks/MarkPopover.vue'
import IconArrowDown from '../icons/IconArrowDown.vue'
import IconGroup from '../icons/IconGroup.vue'
import NextNeedsYou from './NextNeedsYou.vue'
import { errorMessage, openInEditor } from '../../api/http'
import { behindCount, behindTitle } from '../../gitSync'
import { markChipText } from '../../conversation/marks'
import { needsYou } from '../../conversation/needsYou'
import { useMinuteClock } from '../../minuteClock'
import { useConversationStore } from '../../stores/conversation'
import { repoLabel, useGitStore } from '../../stores/git'
import { useGroupsStore } from '../../stores/groups'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { displayStateLabel } from '../../sessionState'
import { worktreeLabel } from '../../worktree'

// `detailsOpen`: the Detalhes panel is showing project, group and branch, so the line below the strip stays out.
// `showPath: false` (embedded in the project page): no "Conversas > project" path and no "Próxima" button.
const props = withDefaults(defineProps<{ id: string; detailsOpen?: boolean; showPath?: boolean }>(), { detailsOpen: false, showPath: true })

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const git = useGitStore()
const groups = useGroupsStore()
const now = useMinuteClock()

const listed = computed(() => sessions.find(props.id))
const conv = computed(() => conversations.get(props.id))
const title = computed(() => conv.value?.title ?? listed.value?.title ?? '')
const projectId = computed(() => listed.value?.project_id ?? conv.value?.projectId ?? null)
const project = computed(() => (projectId.value != null ? projects.byId(projectId.value) : undefined))
// Unknown ids (a group this tab has not loaded yet) show nothing.
const group = computed(() => (listed.value?.group_id != null ? groups.byId(listed.value.group_id) : undefined))
const worktree = computed(() => (listed.value ? worktreeLabel(listed.value) : null))
const repos = computed(() => (projectId.value != null ? git.reposFor(projectId.value) : []))
watch(projectId, (id) => { if (id != null) git.ensure(id) }, { immediate: true })
// Announced politely when it changes, for people who cannot see the state icon.
const stateLabel = computed(() => {
  if (!listed.value) return ''
  const state = listed.value.state
  if (state === 'error') return 'Erro'
  if (state === 'awaiting_decision') return 'Aguardando você'
  return displayStateLabel(listed.value)
})
// Branch, worktree and group; the project joins them in the line below the strip when the breadcrumb does not show it.
const hasDetails = computed(() => !!group.value || !!worktree.value || repos.value.length > 0)
const hasMeta = computed(() => !!project.value || hasDetails.value)
const isFinished = computed(() => listed.value?.display_state === 'finished')

const markAt = ref<{ x: number; y: number } | null>(null)
const markButton = ref<HTMLButtonElement | null>(null)
const markChipButton = ref<HTMLButtonElement | null>(null)
const markChip = computed(() => (listed.value ? markChipText(listed.value, new Date()) : null))
// The button and the chip both toggle. The popover leaves their pointerdown alone, so the click closes it instead of reopening.
function toggleMark(event: MouseEvent) {
  if (markAt.value) {
    markAt.value = null
    return
  }
  const trigger = event.currentTarget as HTMLElement
  trigger.focus() // Safari does not focus buttons on click; the popover gives the focus back to this element
  const box = trigger.getBoundingClientRect()
  markAt.value = { x: box.left, y: box.bottom + 4 }
}

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
  // An Esc already handled by a layer above (a dialog, say) is not ours; ours is consumed so the drawer stays.
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault()
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
  <header class="flex w-full flex-col border-b border-line">
    <span data-test="state-live" role="status" aria-live="polite" class="sr-only">{{ stateLabel }}</span>
    <div data-test="header-strip" class="flex min-h-14 items-center gap-3 px-4">
      <DisplayStateIcon v-if="listed" :display="listed.display_state" :size="16" :quiet="!needsYou(listed)" />
      <nav v-if="showPath" data-test="breadcrumb" aria-label="Trilha" class="flex min-w-0 shrink items-center gap-1 text-xs text-fg-muted max-sm:hidden">
        <RouterLink to="/sessions" class="inline-flex min-h-8 shrink-0 items-center no-underline text-fg-muted hover:text-fg">Conversas</RouterLink>
        <template v-if="project">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" aria-hidden="true"><polyline points="9 6 15 12 9 18" /></svg>
          <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="inline-flex min-h-8 min-w-0 items-center gap-1.5 no-underline text-fg-muted hover:text-fg">
            <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" /><span class="truncate">{{ project.name }}</span>
          </RouterLink>
        </template>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" aria-hidden="true"><polyline points="9 6 15 12 9 18" /></svg>
      </nav>
      <input
        v-if="editing"
        ref="input"
        v-model="draft"
        data-test="title-input"
        aria-label="Título da conversa"
        maxlength="200"
        class="h-9 min-w-0 grow rounded-md border border-line-strong bg-elevated px-2.5 text-[1.0625rem] font-semibold text-fg outline-none focus:border-fg-muted"
        @keydown.enter.prevent="saveRename"
        @keydown.esc.prevent="editing = false"
      />
      <h1 v-else class="m-0 min-w-0 grow text-[1.0625rem] leading-snug font-semibold tracking-tight">
        <button
          type="button"
          data-test="conversation-title"
          title="Clique para renomear"
          class="block min-h-8 max-w-full truncate text-left decoration-fg-subtle underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-primary"
          @click="startRename"
        >{{ title }}</button>
      </h1>
      <button v-if="markChip" ref="markChipButton" type="button" data-test="mark-chip" aria-haspopup="menu" :aria-expanded="!!markAt" class="flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-line px-2 text-xs text-fg-muted hover:bg-card" @click="toggleMark">
        <MarkIcon v-if="listed?.mark" :mark="listed.mark" />{{ markChip }}
      </button>
      <span v-if="listed?.priority" data-test="header-priority" role="img" title="Prioridade" aria-label="Prioridade" class="shrink-0 text-fg-muted"><MarkIcon mark="priority" :size="13" /></span>
      <span v-if="copied" role="status" class="shrink-0 text-xs text-primary-soft">ID copiado</span>
      <NextNeedsYou v-if="showPath" :current-id="id" />
      <button v-if="listed" ref="markButton" type="button" data-test="mark-button" aria-haspopup="menu" :aria-expanded="!!markAt" class="h-8 shrink-0 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="toggleMark">Marcar</button>
      <button
        v-if="listed"
        type="button"
        data-test="toggle-finished"
        class="h-8 shrink-0 rounded-md border border-line-strong px-3 text-sm font-medium hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-40"
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
          title="Mais ações"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          @click="menuOpen = !menuOpen"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg>
        </button>
        <div
          v-if="menuOpen"
          role="menu"
          class="absolute right-0 z-20 mt-1 flex w-56 flex-col rounded-lg border border-line-strong bg-card py-1 shadow-lg"
        >
          <button type="button" role="menuitem" data-test="menu-editor" class="px-3 py-2 text-left text-sm hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted" :disabled="!project" @click="openProject">Abrir projeto no editor</button>
          <button type="button" role="menuitem" data-test="menu-copy-id" class="px-3 py-2 text-left text-sm hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted" @click="copyId">Copiar ID da sessão</button>
        </div>
      </div>
      <slot name="details-toggle" />
    </div>
    <div
      v-if="!detailsOpen && hasMeta"
      data-test="header-meta"
      class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-2 text-xs text-fg-muted"
      :class="{ 'sm:hidden': showPath && !hasDetails }"
    >
      <!-- With the breadcrumb (from 640px up) the project is already in the strip; below that the breadcrumb is hidden. -->
      <span v-if="project" data-test="header-project" class="flex items-center gap-1.5" :class="{ 'sm:hidden': showPath }">
        <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />{{ project.name }}
      </span>
      <span v-if="group" data-test="header-group" class="flex items-center gap-1.5">
        <IconGroup :size="12" class="shrink-0 text-fg-subtle" />{{ group.name }}
      </span>
      <span v-if="worktree" data-test="header-worktree" class="flex items-center" :title="listed?.worktree_path ?? undefined">
        <WorktreeLabel :text="worktree" />
      </span>
      <template v-else>
        <span v-for="repo in repos" :key="repo.path" class="flex items-center">
          <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
          <span
            v-if="behindCount(repo) > 0"
            data-test="header-behind"
            :title="behindTitle(repo, now)"
            class="ml-1.5 inline-flex shrink-0 items-center gap-1 rounded-full border border-line-strong py-px pr-2 pl-1.5 font-mono text-xs tabular-nums text-secondary-soft"
          ><IconArrowDown :size="11" />{{ behindCount(repo) }} para baixar</span>
        </span>
      </template>
    </div>
    <p v-if="error" data-test="header-error" role="alert" class="m-0 px-4 pb-2 text-sm text-diff-del-fg">{{ error }}</p>
    <p
      v-if="conv?.externalActivity"
      data-test="external-activity"
      role="status"
      class="m-0 border-t border-secondary/40 bg-secondary-tint px-4 py-2 text-xs text-secondary-soft"
    >Esta sessão foi modificada fora do app no último minuto. Usar a mesma sessão no CLI e aqui ao mesmo tempo pode embaralhar o histórico.</p>
    <MarkPopover v-if="markAt && listed" :session="listed" :x="markAt.x" :y="markAt.y" :ignore="[markButton, markChipButton]" @close="markAt = null" />
  </header>
</template>
