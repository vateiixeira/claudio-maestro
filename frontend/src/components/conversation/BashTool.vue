<script setup lang="ts">
import { computed, ref } from 'vue'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()
const open = ref(true)

const output = computed(() => resultText(props.item.result?.content))
const running = computed(() => props.item.streaming || (!props.item.result && props.sessionActive))
const isError = computed(() => props.item.result?.is_error === true)
</script>

<template>
  <div
    class="overflow-hidden rounded-lg border bg-panel"
    :class="isError ? 'border-diff-del-fg/40' : running ? 'border-primary/40' : 'border-line'"
  >
    <div class="flex items-center gap-2 border-b border-line px-3 py-2">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" :class="running ? 'text-primary-soft' : 'text-fg-muted'" aria-hidden="true"><path d="m4 17 6-6-6-6" /><line x1="12" y1="19" x2="20" y2="19" /></svg>
      <span class="text-xs font-semibold text-fg-muted">Comando</span>
      <span v-if="str(item.input.description)" class="min-w-0 truncate text-xs text-fg-muted">· {{ str(item.input.description) }}</span>
      <span class="grow" />
      <span v-if="running" class="animate-pulse text-xs text-primary-soft">rodando…</span>
      <span v-else-if="isError" class="text-xs text-diff-del-fg">falhou</span>
      <span v-else-if="!item.result" class="text-xs text-fg-muted">sem resultado</span>
      <button
        v-if="!running && output"
        type="button"
        data-test="toggle-output"
        class="cursor-pointer border-none bg-transparent p-0 text-xs text-fg-muted hover:text-fg"
        :aria-expanded="open"
        @click="open = !open"
      >
        {{ open ? 'Recolher saída' : 'Ver saída' }}
      </button>
    </div>
    <div class="px-3 py-2">
      <pre class="m-0 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all text-fg">$ {{ str(item.input.command) }}</pre>
      <div v-if="open && output" class="mt-1" :class="isError ? 'rounded-md bg-diff-del-bg px-2 py-1 text-diff-del-fg' : 'text-fg-muted'" :data-test="isError ? 'tool-error' : 'tool-output'">
        <TruncatedText :text="output" />
      </div>
    </div>
  </div>
</template>
