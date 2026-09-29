<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import OptionMenu, { type MenuOption } from './session/OptionMenu.vue'
import { errorMessage, sendMessage, updateSession } from '../api/http'
import { type DraftImage, MAX_IMAGES, MAX_TOTAL_BYTES, base64Of, filesFrom, imageProblem, readImage } from '../conversation/images'
import { setPendingDraft } from '../conversation/pendingDrafts'
import { clearDraft, loadDraft, loadLastProject, saveDraft, saveLastProject, type ConversationDraft } from '../newConversationDraft'
import { ALL_EFFORTS, EFFORT_LABELS, MODE_LABELS, SELECTABLE_MODES } from '../sessionOptions'
import { useModelsStore } from '../stores/models'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { Effort, PermissionMode, SessionUpdate } from '../types/api'

const store = useNewConversationStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const models = useModelsStore()
const router = useRouter()
void models.ensure()

const available = computed(() => projects.projects.filter((p) => p.available))
const draft = ref<ConversationDraft>(loadDraft())
const images = ref<DraftImage[]>([])
const error = ref<string | null>(null)
const submitting = ref(false)
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
onMounted(async () => {
  pickProject()
  await nextTick()
  promptEl.value?.focus()
})
watch(draft, (value) => saveDraft(value), { deep: true })
// Projects that load after the modal opened, or one that becomes unavailable while it is open.
watch(available, () => {
  if (!available.value.some((p) => p.id === draft.value.projectId)) pickProject()
})

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
  let total = images.value.reduce((sum, i) => sum + i.size, 0)
  for (const file of files) {
    const problem = imageProblem(file)
    if (problem) { error.value = problem; continue }
    if (images.value.length >= MAX_IMAGES || total + file.size > MAX_TOTAL_BYTES) { error.value = 'Imagens demais para uma mensagem.'; break }
    total += file.size
    images.value.push(await readImage(file))
  }
}
function onPaste(event: ClipboardEvent) {
  const files = filesFrom(event.clipboardData)
  if (!files.length) return
  event.preventDefault()
  void addFiles(files)
}

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
  submitting.value = true
  error.value = null
  const { projectId, title, prompt, model, effort, permissionMode } = draft.value
  let sessionId: string
  try {
    sessionId = (await sessions.create(projectId!)).session_id
  } catch (e) {
    error.value = errorMessage(e)
    submitting.value = false
    return
  }
  saveLastProject(projectId!)
  try {
    const changes: SessionUpdate = {}
    if (title.trim()) changes.title = title.trim()
    if (model) changes.model = model
    if (effort) changes.effort = effort
    if (permissionMode) changes.permission_mode = permissionMode
    if (Object.keys(changes).length) await updateSession(sessionId, changes)
    await sendMessage(sessionId, prompt, images.value.map((i) => ({ media_type: i.mediaType, data: base64Of(i) })))
  } catch (e) {
    // The session exists: open it with the prompt waiting in its composer.
    setPendingDraft(sessionId, { text: prompt, error: errorMessage(e) })
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
function discard() {
  finish()
  opener?.focus()
}
function close() {
  store.close()
  opener?.focus()
}

// Tab stays inside the dialog: from the last control it wraps to the first, and back.
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialogEl.value) return
  const list = Array.from(dialogEl.value.querySelectorAll<HTMLElement>('button:not([disabled]):not([tabindex="-1"]), input, select, textarea, a[href]'))
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
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @keydown.esc.prevent="close" @keydown="onKeydown" @click.self="close">
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
        <button type="button" data-test="nc-close" aria-label="Fechar" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="close">×</button>
      </header>

      <div v-if="available.length === 0" data-test="nc-no-projects" class="flex flex-col gap-3 px-5 py-6">
        <p class="m-0">Cadastre um projeto antes de iniciar uma conversa.</p>
        <RouterLink to="/projects/new" class="text-primary-soft" @click="close">Cadastrar projeto</RouterLink>
      </div>
      <template v-else>
        <div class="flex min-h-0 grow flex-col gap-3 overflow-y-auto px-5 py-4">
          <label class="flex items-center gap-2 text-sm text-fg-muted">
            em
            <select v-model.number="draft.projectId" data-test="nc-project" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg">
              <option v-for="p in available" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <input v-model="draft.title" data-test="nc-title" placeholder="Título (opcional)" aria-label="Título (opcional)" maxlength="200" class="h-10 rounded-md border border-line-strong bg-bg px-3 text-base font-semibold text-fg outline-none focus:border-primary" />
          <textarea
            ref="promptEl"
            v-model="draft.prompt"
            data-test="nc-prompt"
            aria-label="Prompt"
            placeholder="O que você quer fazer? (Ctrl+V cola imagens)"
            class="min-h-40 grow resize-none rounded-md border border-line-strong bg-bg px-3 py-2 text-sm leading-relaxed text-fg outline-none focus:border-primary"
            @keydown="onPromptKey"
            @paste="onPaste"
          />
          <p v-if="images.length" class="m-0 text-xs text-fg-muted">{{ images.length }} {{ images.length === 1 ? 'imagem anexada' : 'imagens anexadas' }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <OptionMenu name="Modelo" :text="modelText" :options="modelOptions" :selected="draft.model ?? 'default'" @select="(v) => (draft.model = v === 'default' ? null : v)" />
            <OptionMenu name="Raciocínio" :text="`Raciocínio ${draft.effort ? EFFORT_LABELS[draft.effort] : 'padrão'}`" :options="effortOptions" :selected="draft.effort ?? 'default'" @select="(v) => (draft.effort = v === 'default' ? null : (v as Effort))" />
            <OptionMenu name="Modo" :text="draft.permissionMode ? MODE_LABELS[draft.permissionMode] : 'Modo padrão'" :options="modeOptions" :selected="draft.permissionMode ?? 'default-account'" @select="(v) => (draft.permissionMode = v === 'default-account' ? null : (v as PermissionMode))" />
          </div>
          <p v-if="error" data-test="nc-error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
        </div>
        <footer class="flex items-center gap-3 border-t border-line px-5 py-3">
          <button type="button" data-test="nc-discard" class="h-10 rounded-md px-3 text-sm text-fg-muted hover:text-fg" @click="discard">Descartar rascunho</button>
          <span class="grow" />
          <button type="button" data-test="nc-submit" class="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:opacity-40" :disabled="!canSubmit" @click="submit">{{ submitting ? 'Iniciando…' : 'Iniciar conversa' }}</button>
        </footer>
      </template>
    </div>
  </div>
</template>
