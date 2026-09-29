<script setup lang="ts">
import { computed, ref } from 'vue'
import { countLines, resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'

const props = defineProps<{ item: ToolItem }>()
const open = ref(false)

const content = computed(() => resultText(props.item.result?.content))
const lineCount = computed(() => countLines(content.value))
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line bg-panel">
    <button
      type="button"
      class="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-fg"
      :aria-expanded="open"
      :disabled="!item.result"
      @click="open = !open"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></svg>
      <span class="text-xs font-semibold text-fg-muted">Leitura</span>
      <span class="min-w-0 grow truncate font-mono text-xs">{{ str(item.input.file_path) }}</span>
      <span v-if="!item.result" class="text-xs text-primary-soft">lendo…</span>
      <span v-else-if="item.result.is_error" class="text-xs text-diff-del-fg">erro</span>
      <span v-else class="text-xs text-fg-muted">{{ lineCount }} {{ lineCount === 1 ? 'linha' : 'linhas' }}</span>
    </button>
    <div v-if="open && item.result" class="border-t border-line px-3 py-2" :class="{ 'text-diff-del-fg': item.result.is_error }">
      <TruncatedText :text="content" />
    </div>
  </div>
</template>
