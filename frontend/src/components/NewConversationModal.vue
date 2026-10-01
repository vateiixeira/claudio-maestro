<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import OptionMenu, { type MenuOption } from './session/OptionMenu.vue'
import { errorMessage, sendMessage, updateSession } from '../api/http'
import { type DraftImage, IMAGE_TYPES, attachImages, base64Of, filesFrom, formatSize } from '../conversation/images'
import { useDictation } from '../conversation/dictation'
import { rememberSentImages } from '../conversation/localImages'
import { setPendingDraft } from '../conversation/pendingDrafts'
import { sortGroups } from '../groupList'
import { clearDraft, loadDraft, loadLastProject, saveDraft, saveLastProject, type ConversationDraft } from '../newConversationDraft'
import { ALL_EFFORTS, EFFORT_LABELS, MODE_LABELS, SELECTABLE_MODES } from '../sessionOptions'
import { useGroupsStore } from '../stores/groups'
import { useModelsStore } from '../stores/models'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { Effort, PermissionMode, SessionUpdate } from '../types/api'

const store = useNewConversationStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const models = useModelsStore()
const groups = useGroupsStore()
const router = useRouter()
void models.ensure()

const available = computed(() => projects.projects.filter((p) => p.available))
const draft = ref<ConversationDraft>(loadDraft())
const images = ref<DraftImage[]>([])
const error = ref<string | null>(null)
const submitting = ref(false)
// Once the session exists it is kept across attempts, so a retry does not create a second one.
const createdId = ref<string | null>(null)
const optionsApplied = ref(false)
// Why the title and options were not applied, for the message shown if the user leaves before a retry.
const optionsError = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const fullscreen = ref(false)
const promptEl = ref<HTMLTextAreaElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
// Where focus was before the modal opened; it goes back there when the modal closes.
const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
const lastProject = loadLastProject()

// The project: the one asked for, else the draft's, else the last used, else the first available. Never one that is gone.
function pickProject() {
  const ids = available.value.map((p) => p.id)
  const wanted = [store.presetProjectId, draft.value.projectId, lastProject].find((id) => id != null && ids.includes(id))
  draft.value.projectId = wanted ?? ids[0] ?? null
}
// The groups of the chosen project, most recently active first.
const projectGroups = computed(() =>
  draft.value.projectId == null ? [] : sortGroups(groups.forProject(draft.value.projectId), sessions.forProject(draft.value.projectId)),
)
// The group: the one asked for (`null` = none, whatever the draft says), else the draft's, when it belongs to
// the chosen project. While the groups are still loading nothing is known, so the choice is kept as it is and
// picked again once they arrive.
function pickGroup() {
  const wanted = store.presetGroupId === undefined ? draft.value.groupId : store.presetGroupId
  if (!groups.loaded) {
    draft.value.groupId = wanted
    return
  }
  const ids = projectGroups.value.map((g) => g.id)
  draft.value.groupId = wanted != null && ids.includes(wanted) ? wanted : null
}
onMounted(async () => {
  pickProject()
  pickGroup()
  await nextTick()
  promptEl.value?.focus()
})
watch(draft, (value) => saveDraft(value), { deep: true })
watch(
  () => groups.loaded,
  (loaded) => {
    if (loaded && createdId.value === null) pickGroup()
  },
)
// Projects that load after the modal opened, or one that becomes unavailable while it is open.
watch(available, () => {
  if (!available.value.some((p) => p.id === draft.value.projectId)) {
    pickProject()
    pickGroup()
  }
})
// A group removed while the modal is open.
watch(
  () => projectGroups.value.map((g) => g.id),
  (ids) => {
    if (groups.loaded && draft.value.groupId != null && !ids.includes(draft.value.groupId)) draft.value.groupId = null
  },
)

const modelOptions = computed<MenuOption[]>(() => [
  { value: 'default', label: 'Padrão' },
  ...models.models.map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])
const modelText = computed(() => models.models.find((m) => m.value === draft.value.model)?.displayName ?? 'Padrão')
const effortOptions = computed<MenuOption[]>(() => [
  { value: 'default', label: 'Padrão' },
  ...ALL_EFFORTS.map((e) => ({ value: e, label: EFFORT_LABELS[e] })),
])
// "Sem perguntas" needs a confirmation: it is only offered inside the conversation.
const modeOptions: MenuOption[] = [
  { value: 'default-account', label: 'Padrão da conta' },
  ...SELECTABLE_MODES.map((m) => ({ value: m, label: MODE_LABELS[m] })),
]

const canSubmit = computed(() => !submitting.value && draft.value.projectId != null && (draft.value.prompt.trim() !== '' || images.value.length > 0))

async function addFiles(files: File[]) {
  const { error: problem } = await attachImages(() => images.value, files)
  error.value = problem
}
function removeImage(id: number) {
  images.value = images.value.filter((i) => i.id !== id)
}
function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = '' // picking the same file again must fire `change` again
  if (files.length) void addFiles(files)
}
// The overlay takes the drop of files, so one dropped anywhere on it is not opened by the browser.
// Text is left alone: dragging it into the prompt or the title keeps working.
function hasFiles(event: DragEvent) {
  return Boolean(event.dataTransfer?.types?.includes('Files'))
}
function onDragOver(event: DragEvent) {
  if (hasFiles(event)) event.preventDefault()
}
function onDrop(event: DragEvent) {
  if (!hasFiles(event)) return
  event.preventDefault()
  const files = filesFrom(event.dataTransfer)
  if (files.length) void addFiles(files)
}
function onPaste(event: ClipboardEvent) {
  const files = filesFrom(event.clipboardData)
  if (!files.length) return
  event.preventDefault()
  void addFiles(files)
}

const dictation = useDictation({
  begin() {
    const el = promptEl.value
    return { text: draft.value.prompt, cursor: el?.selectionStart ?? draft.value.prompt.length }
  },
  update(value, cursor) {
    draft.value.prompt = value
    const el = promptEl.value
    if (el) {
      el.value = value
      el.setSelectionRange(cursor, cursor)
    }
  },
})
function stopDictation() {
  if (dictation.recording.value) dictation.stop()
}
// Typing while dictating stops it, so it does not overwrite what was typed.
function onPromptInput() {
  stopDictation()
}
// The modal stays mounted while closed: closing it by any path stops the dictation.
watch(() => store.isOpen, (open) => { if (!open) stopDictation() })

function onPromptKey(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return
  if (event.shiftKey) return // the browser inserts the line break
  event.preventDefault()
  if (event.ctrlKey || event.metaKey || event.altKey) {
    const el = event.target as HTMLTextAreaElement
    const start = el.selectionStart ?? draft.value.prompt.length
    const end = el.selectionEnd ?? start
    draft.value.prompt = draft.value.prompt.slice(0, start) + '\n' + draft.value.prompt.slice(end)
    void nextTick(() => el.setSelectionRange(start + 1, start + 1))
  } else {
    void submit()
  }
}

async function submit() {
  if (!canSubmit.value) return
  stopDictation()
  submitting.value = true
  error.value = null
  const { projectId, groupId, title, prompt, model, effort, permissionMode } = draft.value
  if (createdId.value === null) {
    try {
      createdId.value = (await sessions.create(projectId!, groupId)).session_id
    } catch (e) {
      error.value = errorMessage(e)
      submitting.value = false
      return
    }
    saveLastProject(projectId!)
  }
  const sessionId = createdId.value
  // Title and options come before the first message, which must run with them. If they fail the
  // modal stays open with everything the user typed; the next attempt reuses the created session.
  if (!optionsApplied.value) {
    const changes: SessionUpdate = {}
    if (title.trim()) changes.title = title.trim()
    if (model) changes.model = model
    if (effort) changes.effort = effort
    if (permissionMode) changes.permission_mode = permissionMode
    try {
      if (Object.keys(changes).length) await updateSession(sessionId, changes)
      optionsApplied.value = true
    } catch (e) {
      optionsError.value = errorMessage(e)
      error.value = `A conversa foi criada, mas não foi possível aplicar o título e as opções. ${optionsError.value} Clique em Iniciar conversa para tentar de novo.`
      submitting.value = false
      return
    }
  }
  const attached = [...images.value]
  // Registered before the request: the user item may arrive over the socket first.
  const forget = attached.length ? rememberSentImages(sessionId, attached.map((i) => ({ url: i.url, mediaType: i.mediaType, size: i.size }))) : () => {}
  try {
    await sendMessage(sessionId, prompt, attached.map((i) => ({ media_type: i.mediaType, data: base64Of(i) })))
  } catch (e) {
    // The session exists: open it with the prompt and the images waiting in its composer.
    forget()
    setPendingDraft(sessionId, { text: prompt, error: errorMessage(e), images: attached })
  }
  finish()
  await router.push({ name: 'session', params: { id: sessionId } })
}

// Clears the saved draft and closes. The draft ref is left as is: changing it
// would make the watcher save it again. The next opening mounts a fresh modal.
function finish() {
  clearDraft()
  submitting.value = false
  store.close()
}
// The session was created but the title and options were not applied: it exists, empty, and has no
// delete route. Leaving the modal opens it with the prompt and the images waiting in its composer,
// so nothing stays orphaned or hidden.
async function leaveToCreated(sessionId: string) {
  const reason = optionsError.value ? ` ${optionsError.value}` : ''
  const message = `A conversa foi criada, mas não foi possível aplicar o título e as opções.${reason} Envie a mensagem para começar e ajuste as opções aqui.`
  setPendingDraft(sessionId, { text: draft.value.prompt, error: message, images: images.value })
  finish()
  opener?.focus()
  await router.push({ name: 'session', params: { id: sessionId } })
}
// Neither Esc, × nor the backdrop closes the modal while a request is out.
function close() {
  if (submitting.value) return
  if (createdId.value !== null) {
    void leaveToCreated(createdId.value)
    return
  }
  store.close()
  opener?.focus()
}
function discard() {
  if (submitting.value) return
  if (createdId.value !== null) {
    void leaveToCreated(createdId.value)
    return
  }
  finish()
  opener?.focus()
}

// Tab stays inside the dialog: from the last control it wraps to the first, and back.
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialogEl.value) return
  const list = Array.from(dialogEl.value.querySelectorAll<HTMLElement>('button:not([disabled]):not([tabindex="-1"]), input:not([type=file]), select, textarea, a[href]'))
  const first = list[0]
  const last = list[list.length - 1]
  if (!first || !last) return
  const active = document.activeElement
  if (event.shiftKey && (active === first || !dialogEl.value.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !dialogEl.value.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @keydown.esc.prevent="close" @keydown="onKeydown" @click.self="close" @dragover="onDragOver" @drop="onDrop">
    <div
      ref="dialogEl"
      data-test="new-conversation-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="nc-heading"
      class="flex max-h-full w-full flex-col rounded-xl border border-line-strong bg-panel shadow-2xl"
      :class="fullscreen ? 'h-full max-w-none' : 'max-w-2xl'"
    >
      <header class="flex items-center gap-2 border-b border-line px-5 py-3">
        <h2 id="nc-heading" class="m-0 grow text-base font-semibold">Nova conversa</h2>
        <button type="button" :aria-label="fullscreen ? 'Sair da tela cheia' : 'Tela cheia'" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="fullscreen = !fullscreen">⤢</button>
        <button type="button" data-test="nc-close" aria-label="Fechar" :disabled="submitting" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card disabled:opacity-40" @click="close">×</button>
      </header>

      <div v-if="available.length === 0" data-test="nc-no-projects" class="flex flex-col gap-3 px-5 py-6">
        <p class="m-0">Cadastre um projeto antes de iniciar uma conversa.</p>
        <RouterLink to="/projects/new" class="text-info-soft" @click="close">Cadastrar projeto</RouterLink>
      </div>
      <template v-else>
        <div class="flex min-h-0 grow flex-col gap-3 overflow-y-auto px-5 py-4">
          <label class="flex items-center gap-2 text-sm text-fg-muted">
            em
            <select v-model.number="draft.projectId" data-test="nc-project" :disabled="createdId !== null" @change="draft.groupId = null" :title="createdId !== null ? 'A conversa já foi criada neste projeto.' : undefined" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg">
              <option v-for="p in available" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <label v-if="projectGroups.length" class="flex items-center gap-2 text-sm text-fg-muted">
            agrupador
            <select v-model="draft.groupId" data-test="nc-group" aria-label="Agrupador" :disabled="createdId !== null" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg">
              <option :value="null">Nenhum</option>
              <option v-for="g in projectGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </label>
          <input v-model="draft.title" data-test="nc-title" placeholder="Título (opcional)" aria-label="Título (opcional)" maxlength="200" class="h-10 rounded-md border border-line-strong bg-elevated px-3 text-base font-semibold text-fg outline-none focus:border-fg-muted" />
          <textarea
            ref="promptEl"
            v-model="draft.prompt"
            data-test="nc-prompt"
            aria-label="Prompt"
            placeholder="O que você quer fazer? (Ctrl+V cola imagens)"
            class="min-h-40 grow resize-none rounded-md border border-line-strong bg-elevated px-3 py-2 text-sm leading-relaxed text-fg outline-none focus:border-fg-muted"
            @input="onPromptInput"
            @keydown="onPromptKey"
            @paste="onPaste"
          />
          <div v-if="images.length" class="flex flex-wrap gap-2">
            <div v-for="image in images" :key="image.id" data-test="attachment-draft" class="flex items-center gap-2.5 rounded-lg border border-line-strong bg-card p-1.5">
              <img :src="image.url" alt="" class="size-11 rounded-md bg-line object-cover" />
              <div class="flex min-w-0 flex-col">
                <span class="max-w-40 truncate text-[13px] font-medium">{{ image.name }}</span>
                <span class="text-xs text-fg-muted">{{ formatSize(image.size) }}</span>
              </div>
              <button type="button" :aria-label="`Remover imagem ${image.name}`" class="flex size-11 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-fg-muted hover:bg-elevated hover:text-fg" @click="removeImage(image.id)">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
              </button>
            </div>
          </div>
          <p v-if="images.length" data-test="nc-images-note" class="m-0 text-xs text-fg-muted">As imagens não ficam guardadas no rascunho: se você fechar o modal, elas se perdem.</p>
          <div class="flex flex-wrap items-center gap-2">
            <input ref="fileInput" type="file" data-test="nc-file-input" :accept="IMAGE_TYPES.join(',')" multiple tabindex="-1" class="hidden" @change="onPick" />
            <button type="button" data-test="nc-attach" aria-label="Anexar imagem" title="Anexar imagem" class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong bg-transparent px-2.5 text-sm text-fg-muted hover:text-fg" @click="fileInput?.click()">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l9-9a3.3 3.3 0 0 1 4.7 4.7l-9 9a1.7 1.7 0 0 1-2.4-2.4l8.3-8.3" /></svg>
              Imagem
            </button>
            <button
              v-if="dictation.supported"
              type="button"
              data-test="nc-dictate"
              :aria-label="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
              :aria-pressed="dictation.recording.value"
              :title="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
              class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-sm"
              :class="dictation.recording.value ? 'border-secondary/60 bg-secondary-tint text-secondary' : 'border-line-strong bg-transparent text-fg-muted hover:text-fg'"
              @click="dictation.toggle"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              Ditar
            </button>
            <OptionMenu name="Modelo" :text="modelText" :options="modelOptions" :selected="draft.model ?? 'default'" @select="(v) => (draft.model = v === 'default' ? null : v)" />
            <OptionMenu name="Raciocínio" :text="`Raciocínio ${draft.effort ? EFFORT_LABELS[draft.effort] : 'padrão'}`" :options="effortOptions" :selected="draft.effort ?? 'default'" @select="(v) => (draft.effort = v === 'default' ? null : (v as Effort))" />
            <OptionMenu name="Modo" :text="draft.permissionMode ? MODE_LABELS[draft.permissionMode] : 'Modo padrão'" :options="modeOptions" :selected="draft.permissionMode ?? 'default-account'" @select="(v) => (draft.permissionMode = v === 'default-account' ? null : (v as PermissionMode))" />
          </div>
          <span v-if="dictation.recording.value" data-test="nc-recording" role="status" class="flex items-center gap-1.5 text-xs text-secondary">
            <span class="size-2 animate-pulse rounded-full bg-secondary" aria-hidden="true" />Gravando… clique no microfone para parar
          </span>
          <p v-else-if="dictation.error.value" role="alert" class="m-0 text-sm text-diff-del-fg">{{ dictation.error.value }}</p>
          <p v-if="error" data-test="nc-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
        </div>
        <footer class="flex items-center gap-3 border-t border-line px-5 py-3">
          <button type="button" data-test="nc-discard" :disabled="submitting" class="h-10 rounded-md px-3 text-sm text-fg-muted hover:text-fg disabled:opacity-40" @click="discard">Descartar rascunho</button>
          <span class="grow" />
          <button type="button" data-test="nc-submit" class="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:opacity-40" :disabled="!canSubmit" @click="submit">{{ submitting ? 'Iniciando…' : 'Iniciar conversa' }}</button>
        </footer>
      </template>
    </div>
  </div>
</template>
