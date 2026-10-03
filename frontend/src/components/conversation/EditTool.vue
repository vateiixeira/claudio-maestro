<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import DiffLines from './DiffLines.vue'
import WorkHeader from './WorkHeader.vue'
import { SESSION_ID_KEY, useChangesPanelStore } from '../../stores/changesPanel'
import { diffCounts, toolDiff } from '../../conversation/diff'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()

const LIMIT = 200
const DIFF_PREVIEW = 40
const NEW_FILE_PREVIEW = 12
const lines = computed(() => toolDiff(props.item.name, props.item.input, props.item.result?.details ?? null))
const counts = computed(() => diffCounts(lines.value))
const label = computed(() => (props.item.name === 'Write' ? 'Escrita' : 'Edição'))
const isError = computed(() => props.item.result?.is_error === true)
// A Write that created the file: shown as plain text, not as a diff. The backend says so with `details.type`;
// only when it does not, a Write that is all additions counts as new. A Write that failed never does.
const isNewFile = computed(() => {
  if (props.item.name !== 'Write' || isError.value) return false
  const kind = props.item.result?.details?.type
  if (typeof kind === 'string') return kind === 'create'
  return lines.value.length > 0 && lines.value.every((l) => l.kind === 'add')
})
// Long output starts as a preview; expanded it still stops at LIMIT until the user asks for all.
const expanded = ref(false)
const showAll = ref(false)
const previewSize = computed(() => (isNewFile.value ? NEW_FILE_PREVIEW : DIFF_PREVIEW))
const hasMore = computed(() => lines.value.length > previewSize.value)
const previewing = computed(() => hasMore.value && !expanded.value)
const truncated = computed(() => expanded.value && !showAll.value && lines.value.length > LIMIT)
const shown = computed(() => {
  if (previewing.value) return lines.value.slice(0, previewSize.value)
  return truncated.value ? lines.value.slice(0, LIMIT) : lines.value
})
const newFileText = computed(() => shown.value.map((l) => l.text).join('\n'))
function collapse() {
  expanded.value = false
  showAll.value = false
}
const button = 'min-h-8 cursor-pointer rounded-md border border-line-strong bg-transparent px-2.5 py-1 text-xs text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-primary'
const sessionId = inject(SESSION_ID_KEY, null)
// Only columns provide the session id; outside them there is no panel to open.
const panel = sessionId ? useChangesPanelStore() : null
function viewChanges() {
  if (sessionId) panel?.open(sessionId.value, props.item)
}
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const status = computed<'ok' | 'running' | 'error' | 'idle'>(() => {
  if (running.value) return 'running'
  if (isError.value) return 'error'
  return props.item.result ? 'ok' : 'idle'
})
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line bg-panel">
    <WorkHeader kind="edit" :label="label" :desc="str(item.input.file_path)" mono :status="status">
      <template #trail>
        <span v-if="item.result_missing" data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
        <span class="shrink-0 font-mono text-xs text-diff-add-fg">+{{ counts.added }}</span>
        <span class="shrink-0 font-mono text-xs text-diff-del-fg">−{{ counts.removed }}</span>
      </template>
      <template v-if="sessionId" #actions>
        <button
          type="button"
          data-test="view-changes"
          class="shrink-0 cursor-pointer rounded-md border border-line-strong bg-transparent px-2 py-0.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
          @click="viewChanges"
        >Ver alterações</button>
      </template>
    </WorkHeader>
    <p v-if="isError" data-test="tool-error" class="m-0 border-t border-line bg-diff-del-bg px-3 py-2 font-mono text-xs text-diff-del-fg whitespace-pre-wrap">{{ resultText(item.result?.content) }}</p>
    <div v-if="isNewFile" data-test="new-file-preview" class="border-t border-line px-3 py-2">
      <pre class="m-0 font-mono text-xs leading-[1.7] text-fg-muted whitespace-pre-wrap break-words">{{ newFileText }}</pre>
    </div>
    <div v-else class="border-t border-line"><DiffLines :lines="shown" /></div>
    <div class="flex flex-wrap items-center gap-2 px-3 py-2" :class="{ 'border-t border-line': isNewFile }" v-if="isNewFile || hasMore">
      <span v-if="isNewFile" data-test="new-file-footer" class="mr-auto text-xs text-fg-muted">Novo arquivo · {{ lines.length === 1 ? '1 linha' : `${lines.length} linhas` }}</span>
      <span v-if="truncated" class="text-xs text-fg-muted">Mostrando {{ LIMIT }} de {{ lines.length }} linhas.</span>
      <button v-if="previewing" type="button" data-test="show-lines" :class="button" @click="expanded = true">
        {{ isNewFile ? 'Ver tudo' : `Ver as ${lines.length} linhas` }}
      </button>
      <button v-if="truncated" type="button" data-test="show-all" :class="button" @click="showAll = true">
        Ver tudo ({{ lines.length }} linhas)
      </button>
      <button v-if="hasMore && expanded" type="button" data-test="collapse" :class="button" @click="collapse">Recolher</button>
    </div>
  </div>
</template>
