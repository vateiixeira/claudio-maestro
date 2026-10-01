<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import DiffLines from './DiffLines.vue'
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
// A Write with no previous content is all additions: shown as plain text, not as a diff.
const isNewFile = computed(() => props.item.name === 'Write' && lines.value.length > 0 && lines.value.every((l) => l.kind === 'add'))
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
const isError = computed(() => props.item.result?.is_error === true)
const sessionId = inject(SESSION_ID_KEY, null)
// Only columns provide the session id; outside them there is no panel to open.
const panel = sessionId ? useChangesPanelStore() : null
function viewChanges() {
  if (sessionId) panel?.open(sessionId.value, props.item)
}
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line bg-panel">
    <div class="flex items-center gap-2 border-b border-line px-3 py-2">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-subtle" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
      <span class="cap text-fg">{{ label }}</span>
      <span class="min-w-0 grow truncate font-mono text-xs text-info-soft">{{ str(item.input.file_path) }}</span>
      <span v-if="item.result_missing" data-test="result-missing" class="text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      <span v-else-if="running" class="text-xs text-primary-soft">aplicando…</span>
      <span class="font-mono text-xs text-diff-add-fg">+{{ counts.added }}</span>
      <span class="font-mono text-xs text-diff-del-fg">−{{ counts.removed }}</span>
      <button
        v-if="sessionId"
        type="button"
        data-test="view-changes"
        class="shrink-0 cursor-pointer rounded-md border border-line-strong bg-transparent px-2 py-0.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
        @click="viewChanges"
      >Ver alterações</button>
    </div>
    <p v-if="isError" data-test="tool-error" class="m-0 border-b border-line bg-diff-del-bg px-3 py-2 font-mono text-xs text-diff-del-fg whitespace-pre-wrap">{{ resultText(item.result?.content) }}</p>
    <div v-if="isNewFile" data-test="new-file-preview" class="px-3 py-2">
      <pre class="m-0 font-mono text-xs leading-[1.7] text-fg-muted whitespace-pre-wrap break-words">{{ newFileText }}</pre>
    </div>
    <DiffLines v-else :lines="shown" />
    <div class="flex flex-wrap items-center gap-2 px-3 py-2" :class="{ 'border-t border-line': isNewFile }" v-if="isNewFile || hasMore">
      <span v-if="isNewFile" data-test="new-file-footer" class="mr-auto text-xs text-fg-muted">Novo arquivo · {{ lines.length }} linhas</span>
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
