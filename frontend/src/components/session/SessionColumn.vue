<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from 'vue'
import { SESSION_ID_KEY } from '../../stores/changesPanel'
import { RouterLink } from 'vue-router'
import { ApiError, errorMessage, markSessionSeen } from '../../api/http'
import { useEventSocket } from '../../api/socket'
import SessionStateIcon from '../SessionStateIcon.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { repoLabel, useGitStore } from '../../stores/git'
import ConversationBlock from '../conversation/ConversationBlock.vue'
import MessageComposer from '../conversation/MessageComposer.vue'
import PermissionCard from '../conversation/PermissionCard.vue'
import PlanCard from '../conversation/PlanCard.vue'
import QuestionCard from '../conversation/QuestionCard.vue'
import SessionControls from './SessionControls.vue'
import { deriveDisplay, displayStateLabels } from '../../sessionState'
import { useConversationStore } from '../../stores/conversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { ConversationItem } from '../../types/conversation'

const props = withDefaults(defineProps<{ id: string; visible?: boolean }>(), { visible: true })
const emit = defineEmits<{ close: []; missing: [] }>()

const conversations = useConversationStore()
const projects = useProjectsStore()
const socket = useEventSocket()
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

const loadError = ref<string | null>(null)
const conv = computed(() => conversations.get(props.id))
const project = computed(() => (conv.value?.projectId != null ? projects.byId(conv.value.projectId) : undefined))
const git = useGitStore()
const repos = computed(() => (project.value ? git.reposFor(project.value.id) : []))
watch(() => project.value?.id, (id) => { if (id != null) git.ensure(id) }, { immediate: true })

// "Ver alterações" in an edit card opens the changes panel for this session.
provide(SESSION_ID_KEY, computed(() => props.id))

async function reload() {
  try {
    await conversations.load(props.id)
    loadError.value = null
    markSeenSoon()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      emit('missing')
      return
    }
    loadError.value = errorMessage(e)
  }
}

// Tells the backend the user has looked at this session: after loading, when the
// column gets focus and when new items arrive, but only while the column is visible.
const SEEN_DELAY = 300
let seenTimer: ReturnType<typeof setTimeout> | null = null
const canSee = () => props.visible && document.visibilityState !== 'hidden'
function cancelSeen() {
  if (seenTimer) clearTimeout(seenTimer)
  seenTimer = null
}
function markSeenSoon() {
  if (!canSee()) return
  cancelSeen()
  const id = props.id
  seenTimer = setTimeout(() => {
    seenTimer = null
    if (!canSee() || id !== props.id) return
    markSessionSeen(id).catch(() => {
      // Not worth bothering the user; the next focus or item tries again.
    })
  }, SEEN_DELAY)
}
watch(() => conv.value?.items.length, (length, before) => {
  if (length !== undefined && before !== undefined && length > before) markSeenSoon()
})
// A turn can end by updating existing items only; its result still counts as news.
watch(() => conv.value?.lastResult, (result, before) => {
  if (result && result !== before) markSeenSoon()
})
watch(() => props.visible, (visible) => (visible ? markSeenSoon() : cancelSeen()))
onBeforeUnmount(cancelSeen)

let offs: Array<() => void> = []
watch(
  () => props.id,
  (id) => {
    offs.forEach((off) => off())
    offs = [
      socket.onSession(id, (event) => conversations.receive(event)),
      socket.onReconnect(() => void reload()),
    ]
    loadError.value = null
    void reload()
  },
  { immediate: true },
)
onBeforeUnmount(() => offs.forEach((off) => off()))

// Items with a parent tool are shown inside that tool's block (subagent card or indent).
const tree = computed(() => {
  const items = conv.value?.items ?? []
  const toolIds = new Set(items.flatMap((i) => (i.type === 'tool' ? [i.tool_use_id] : [])))
  const children = new Map<string, ConversationItem[]>()
  const top: ConversationItem[] = []
  for (const item of items) {
    const parent = 'parent_tool_use_id' in item ? item.parent_tool_use_id : null
    if (parent && toolIds.has(parent)) {
      const list = children.get(parent) ?? []
      list.push(item)
      children.set(parent, list)
    } else top.push(item)
  }
  return { top, childrenOf: (toolUseId: string) => children.get(toolUseId) ?? [] }
})
const rows = computed(() => tree.value.top)
const taskList = computed(() => conversations.taskList(props.id))

const footer = computed(() => {
  const result = conv.value?.lastResult
  if (!result) return null
  const parts: string[] = []
  if (result.duration_ms != null) {
    parts.push(`${(result.duration_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`)
  }
  if (result.total_cost_usd != null) {
    parts.push(`US$ ${result.total_cost_usd.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`)
  }
  if (result.is_error) parts.push('terminou com erro')
  return parts.length ? `Último turno: ${parts.join(' · ')}` : null
})

// Follows the end of the conversation only while the user is already there.
const scroller = ref<HTMLElement | null>(null)
const atBottom = ref(true)
function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}
watch(
  () => [conv.value?.seq, conv.value?.items.length, conv.value?.prompts.length],
  async () => {
    if (!atBottom.value) return
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

// Images dropped anywhere on the column go to the message field.
const composer = ref<InstanceType<typeof MessageComposer> | null>(null)
function onDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length || !composer.value) return
  event.preventDefault()
  void composer.value.addFiles(files)
}
function onDragOver(event: DragEvent) {
  if (event.dataTransfer?.types?.includes('Files')) event.preventDefault()
}

function resolvePrompt(promptId: string) {
  conversations.resolvePrompt(props.id, promptId)
}
</script>

<template>
  <section :aria-label="conv ? `Sessão: ${conv.title}` : 'Sessão'" class="flex h-full min-w-0 flex-col" @focusin="markSeenSoon" @dragover="onDragOver" @drop="onDrop">
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

      <div ref="scroller" class="min-h-0 grow overflow-y-auto" @scroll="onScroll">
        <div class="flex flex-col gap-3 p-4">
          <p
            v-if="conv.historyTruncated"
            data-test="history-truncated"
            class="m-0 rounded-md border border-line bg-card px-3 py-1.5 text-center text-xs text-fg-muted"
          >Mostrando as mensagens mais recentes.</p>
          <p v-if="rows.length === 0" class="m-0 py-8 text-center text-sm text-fg-muted">
            Nenhuma mensagem ainda. Escreva abaixo para começar.
          </p>
          <div
            v-for="item in rows"
            :key="item.id"
            class="flex min-w-0 flex-col"
            :class="{ 'border-l border-line pl-4': 'parent_tool_use_id' in item && item.parent_tool_use_id }"
          >
            <ConversationBlock
              :item="item"
              :session-active="conv.state === 'running' || conv.state === 'awaiting_decision'"
              :children-of="tree.childrenOf"
              :task-list="taskList"
            />
          </div>
          <template v-for="prompt in conv.prompts" :key="prompt.prompt_id">
            <QuestionCard
              v-if="prompt.kind === 'question'"
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
            <PlanCard
              v-else-if="prompt.kind === 'plan'"
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
            <PermissionCard
              v-else
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
          </template>
          <p v-if="footer" data-test="turn-footer" class="m-0 font-mono text-xs text-fg-muted">{{ footer }}</p>
        </div>
      </div>

      <div class="flex flex-col gap-2.5 border-t border-line px-4 pt-3 pb-3.5">
        <p
          v-if="conv.state === 'error'"
          data-test="session-error"
          role="alert"
          class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-sm text-diff-del-fg"
        >
          {{ conv.error || 'A sessão parou com erro.' }} Você pode enviar de novo.
        </p>
        <p v-if="loadError" role="alert" class="m-0 text-sm text-secondary-soft">{{ loadError }}</p>
        <MessageComposer ref="composer" :key="conv.sessionId" :session-id="conv.sessionId" :state="conv.state">
          <template #controls><SessionControls :session-id="conv.sessionId" /></template>
        </MessageComposer>
      </div>
    </template>
    <div v-else class="flex flex-col items-start gap-3 px-6 py-8">
      <p v-if="loadError" role="alert" class="m-0 text-fg-muted">{{ loadError }}</p>
      <button
        v-if="loadError"
        type="button"
        aria-label="Fechar coluna"
        class="min-h-9 rounded-md border border-line-strong px-3 text-sm text-fg hover:bg-card"
        @click="emit('close')"
      >
        Fechar coluna
      </button>
      <p v-else class="text-fg-muted">Carregando…</p>
    </div>
  </section>
</template>
