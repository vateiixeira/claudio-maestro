<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, getFileDiff, getSessionChanges, openInEditor } from '../../api/http'
import { diffFromUnified, diffWithoutHunks, toolDiff } from '../../conversation/diff'
import { str } from '../../conversation/tool'
import DiffLines from '../conversation/DiffLines.vue'
import BranchLabel from './BranchLabel.vue'
import { branchText } from '../../stores/git'
import { useChangesPanelStore } from '../../stores/changesPanel'
import { useConversationStore } from '../../stores/conversation'
import type { ChangedFile, ChangesGroup } from '../../types/api'
import type { DiffLine } from '../../conversation/diff'

const props = defineProps<{ sessionId: string }>()

const panel = useChangesPanelStore()
const conversations = useConversationStore()
const conv = computed(() => conversations.get(props.sessionId))

const editLines = computed(() => {
  const item = panel.edit
  return item ? toolDiff(item.name, item.input, item.result?.details ?? null) : []
})

const groups = ref<ChangesGroup[]>([])
const listError = ref<string | null>(null)
const loading = ref(false)
const total = computed(() => {
  let added = 0
  let removed = 0
  for (const group of groups.value) {
    for (const file of group.files) {
      added += file.added ?? 0
      removed += file.removed ?? 0
    }
  }
  return { added, removed }
})

// Each request bumps a generation and aborts the previous one; only the newest
// answer is applied, so late or out-of-order responses are dropped.
let listGen = 0
let listCtrl: AbortController | null = null
let fileGen = 0
let fileCtrl: AbortController | null = null

async function loadChanges() {
  const gen = ++listGen
  listCtrl?.abort()
  const ctrl = (listCtrl = new AbortController())
  loading.value = true
  try {
    const result = await getSessionChanges(props.sessionId, ctrl.signal)
    if (gen !== listGen) return
    groups.value = result.repos
    listError.value = null
    reselect()
  } catch (e) {
    if (gen === listGen) listError.value = errorMessage(e)
  } finally {
    if (gen === listGen) loading.value = false
  }
}

// Selection is kept by group path + file path, so it survives a reload of the list.
const selected = ref<{ group: ChangesGroup; file: ChangedFile } | null>(null)
const fileLines = ref<DiffLine[]>([])
// Shown instead of lines: server notice (file too big) or git's text for a diff without hunks.
const fileNote = ref<string | null>(null)
const fileTruncated = ref(false)
const fileError = ref<string | null>(null)
const editorError = ref<string | null>(null)

function isSelected(group: ChangesGroup, file: ChangedFile): boolean {
  return selected.value?.group.path === group.path && selected.value?.file.path === file.path
}

function reselect() {
  const current = selected.value
  if (!current) return
  for (const group of groups.value) {
    const file = group.files.find((f) => f.path === current.file.path)
    if (group.path === current.group.path && file) {
      void selectFile(group, file)
      return
    }
  }
  clearSelection()
}

function clearSelection() {
  fileGen++
  fileCtrl?.abort()
  selected.value = null
}

async function selectFile(group: ChangesGroup, file: ChangedFile) {
  const gen = ++fileGen
  fileCtrl?.abort()
  fileCtrl = null
  const keep = isSelected(group, file)
  selected.value = { group, file }
  if (!keep) {
    fileLines.value = []
    fileNote.value = null
  }
  fileTruncated.value = false
  fileError.value = null
  editorError.value = null
  const projectId = conv.value?.projectId
  if (group.rel_path == null || projectId == null) return
  const ctrl = (fileCtrl = new AbortController())
  try {
    const result = await getFileDiff(projectId, group.rel_path, file.rel_path, ctrl.signal)
    if (gen !== fileGen) return
    fileLines.value = diffFromUnified(result.diff)
    fileNote.value = result.notice ?? diffWithoutHunks(result.diff)
    fileTruncated.value = result.truncated
  } catch (e) {
    if (gen === fileGen) fileError.value = errorMessage(e)
  }
}

watch(() => props.sessionId, () => {
  clearSelection()
  void loadChanges()
})
// Reload at the end of every turn of the session.
watch(() => conv.value?.lastResult, (result, before) => {
  if (result && result !== before) void loadChanges()
})

onBeforeUnmount(() => {
  listGen++
  fileGen++
  listCtrl?.abort()
  fileCtrl?.abort()
})

async function openSelected() {
  if (!selected.value) return
  editorError.value = null
  try {
    await openInEditor(selected.value.file.path)
  } catch (e) {
    editorError.value = errorMessage(e)
  }
}

void loadChanges()
</script>

<template>
  <aside
    data-test="changes-panel"
    :data-session-id="sessionId"
    aria-label="Painel de alterações"
    class="flex h-full w-[480px] shrink-0 flex-col border-l border-line bg-panel"
  >
    <header class="flex items-center gap-2 border-b border-line px-4 py-3">
      <h2 class="m-0 text-base font-semibold">Alterações</h2>
      <span data-test="changes-total" class="grow font-mono text-xs"><span class="text-diff-add-fg">+{{ total.added }}</span> <span class="text-diff-del-fg">−{{ total.removed }}</span></span>
      <button
        type="button"
        aria-label="Fechar alterações"
        class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="panel.close()"
      >
        <svg viewBox="0 0 16 16" class="size-4" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </header>

    <div class="flex min-h-0 grow flex-col gap-4 overflow-y-auto p-4">
      <section v-if="panel.edit" data-test="edit-diff" class="overflow-hidden rounded-lg border border-line bg-bg">
        <div class="border-b border-line px-3 py-2 font-mono text-xs text-fg-muted truncate">{{ str(panel.edit.input.file_path) }}</div>
        <DiffLines :lines="editLines" />
      </section>

      <section class="flex flex-col gap-2">
        <h3 class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Arquivos modificados na sessão</h3>
        <p v-if="listError" role="alert" class="m-0 text-sm text-secondary-soft">{{ listError }}</p>
        <p v-else-if="!loading && groups.length === 0" class="m-0 text-sm text-fg-muted">Sem alterações</p>
        <div
          v-for="group in groups"
          :key="group.path ?? '-'"
          data-test="changes-repo"
          class="flex flex-col rounded-lg border border-line"
        >
          <div class="flex items-center gap-2 border-b border-line px-3 py-2">
            <span class="min-w-0 truncate font-mono text-xs font-semibold">{{ group.rel_path ?? 'Fora de repositório' }}</span>
            <BranchLabel v-if="group.rel_path != null" :text="branchText({ ...group, error: null })" muted />
          </div>
          <button
            v-for="file in group.files"
            :key="file.path"
            type="button"
            data-test="changed-file"
            class="flex min-h-9 items-center gap-2 border-b border-line px-3 text-left last:border-b-0 hover:bg-card"
            :class="{ 'bg-card': isSelected(group, file) }"
            :aria-pressed="isSelected(group, file)"
            @click="selectFile(group, file)"
          >
            <span class="min-w-0 grow truncate font-mono text-xs">{{ file.rel_path }}</span>
            <span v-if="file.uncommitted" class="shrink-0 text-xs text-secondary-soft">sem commit</span>
            <span v-if="file.added != null" class="font-mono text-xs text-diff-add-fg">+{{ file.added }}</span>
            <span v-if="file.removed != null" class="font-mono text-xs text-diff-del-fg">−{{ file.removed }}</span>
          </button>
        </div>
      </section>

      <section v-if="selected" data-test="file-diff" class="flex flex-col gap-2">
        <div class="flex items-center gap-2">
          <span class="min-w-0 grow truncate font-mono text-xs">{{ selected.file.rel_path }}</span>
          <button
            type="button"
            data-test="open-file-editor"
            class="h-8 shrink-0 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
            @click="openSelected"
          >Abrir no editor</button>
        </div>
        <p v-if="editorError" role="alert" class="m-0 text-sm text-secondary-soft">{{ editorError }}</p>
        <p v-if="fileError" role="alert" class="m-0 text-sm text-secondary-soft">{{ fileError }}</p>
        <p v-else-if="selected.group.rel_path == null" class="m-0 text-sm text-fg-muted">Fora de um repositório git, não há diff contra o último commit.</p>
        <div v-else class="overflow-hidden rounded-lg border border-line bg-bg">
          <p v-if="fileLines.length === 0" class="m-0 px-3 py-2 text-sm text-fg-muted">{{ fileNote ?? 'Sem alterações' }}</p>
          <DiffLines :lines="fileLines" />
          <p v-if="fileTruncated" class="m-0 border-t border-line px-3 py-2 text-xs text-fg-muted">Diff cortado por ser grande demais.</p>
        </div>
      </section>
    </div>
  </aside>
</template>
