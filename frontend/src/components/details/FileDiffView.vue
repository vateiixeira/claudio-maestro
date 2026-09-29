<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, errorMessage, getFileDiff, openInEditor } from '../../api/http'
import { diffFromUnified, diffWithoutHunks, type DiffLine } from '../../conversation/diff'
import DiffLines from '../conversation/DiffLines.vue'
import type { ChangedFile, ChangesGroup } from '../../types/api'

const props = defineProps<{ projectId: number; group: ChangesGroup; file: ChangedFile }>()

const lines = ref<DiffLine[]>([])
const note = ref<string | null>(null)
const truncated = ref(false)
const error = ref<string | null>(null)
const editorError = ref<string | null>(null)
let generation = 0
let controller: AbortController | null = null

async function load() {
  const mine = ++generation
  controller?.abort()
  lines.value = []
  note.value = null
  truncated.value = false
  error.value = null
  if (props.group.rel_path == null) return
  const ctrl = (controller = new AbortController())
  try {
    const result = await getFileDiff(props.projectId, props.group.rel_path, props.file.rel_path, ctrl.signal)
    if (mine !== generation) return
    lines.value = diffFromUnified(result.diff)
    note.value = result.notice ?? diffWithoutHunks(result.diff)
    truncated.value = result.truncated
  } catch (e) {
    if (mine !== generation) return
    error.value = e instanceof ApiError && e.status === 404 && !e.detail ? 'O arquivo não existe mais.' : errorMessage(e)
  }
}

async function openFile() {
  editorError.value = null
  try {
    await openInEditor(props.file.path)
  } catch (e) {
    editorError.value = errorMessage(e)
  }
}

watch(() => [props.group.path, props.file.path], load, { immediate: true })
onBeforeUnmount(() => {
  generation++
  controller?.abort()
})
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <span class="min-w-0 grow truncate font-mono text-xs">{{ file.rel_path }}</span>
      <button
        type="button"
        data-test="open-file-editor"
        class="h-8 shrink-0 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
        @click="openFile"
      >Abrir no editor</button>
    </div>
    <p v-if="editorError" role="alert" class="m-0 text-sm text-secondary-soft">{{ editorError }}</p>
    <p v-if="error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p v-else-if="group.rel_path == null" class="m-0 text-sm text-fg-muted">Fora de um repositório git, não há diff contra o último commit.</p>
    <div v-else class="overflow-hidden rounded-lg border border-line bg-bg">
      <p v-if="lines.length === 0" class="m-0 px-3 py-2 text-sm text-fg-muted">{{ note ?? 'Sem alterações' }}</p>
      <DiffLines :lines="lines" />
      <p v-if="truncated" class="m-0 border-t border-line px-3 py-2 text-xs text-fg-muted">Diff cortado por ser grande demais.</p>
    </div>
  </div>
</template>
