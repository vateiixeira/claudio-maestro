<script setup lang="ts">
import { computed } from 'vue'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()

const output = computed(() => resultText(props.item.result?.content))
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const isError = computed(() => props.item.result?.is_error === true)
</script>

<template>
  <div
    class="overflow-hidden rounded-lg border bg-panel"
    :class="isError ? 'border-diff-del-fg/40' : running ? 'border-primary/40' : 'border-line'"
  >
    <div data-test="bash-header" class="flex items-center gap-2 border-b border-line bg-panel px-3 py-2">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" :class="running ? 'text-primary-soft' : 'text-fg-subtle'" aria-hidden="true"><path d="m4 17 6-6-6-6" /><line x1="12" y1="19" x2="20" y2="19" /></svg>
      <span class="cap text-fg">Comando</span>
      <span v-if="str(item.input.description)" class="min-w-0 truncate text-xs text-fg-subtle">· {{ str(item.input.description) }}</span>
      <span class="grow" />
      <span v-if="item.result_missing" data-test="result-missing" class="text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      <span v-else-if="running" class="animate-pulse text-xs text-primary-soft">rodando…</span>
      <span v-else-if="isError" class="text-xs text-diff-del-fg">falhou</span>
      <span v-else-if="!item.result" class="text-xs text-fg-subtle">sem resultado</span>
    </div>
    <pre data-test="bash-command" class="m-0 bg-bg px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all text-fg"><span data-test="bash-prompt" class="text-fg-subtle">$ </span>{{ str(item.input.command) }}</pre>
    <div v-if="!running && output" data-test="bash-output" class="border-t border-line bg-panel px-3 py-2.5 text-fg-muted">
      <div :data-test="isError ? 'tool-error' : 'tool-output'">
        <TruncatedText :text="output" :variant="isError ? 'error' : 'default'" flat />
      </div>
    </div>
  </div>
</template>
