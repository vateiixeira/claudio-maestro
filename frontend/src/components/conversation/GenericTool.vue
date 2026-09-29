<script setup lang="ts">
import { computed, ref } from 'vue'
import { prettyJson, resultText, toolLabel } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()
const open = ref(false)

const input = computed(() => prettyJson(props.item.input))
const output = computed(() => resultText(props.item.result?.content))
const isError = computed(() => props.item.result?.is_error === true)
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
</script>

<template>
  <div class="overflow-hidden rounded-lg border bg-panel" :class="isError ? 'border-diff-del-fg/40' : 'border-line'">
    <button
      type="button"
      class="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-fg"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span aria-hidden="true" class="text-xs text-fg-muted">{{ open ? '▾' : '▸' }}</span>
      <span class="cap text-fg">Ferramenta</span>
      <span class="min-w-0 grow truncate font-mono text-xs">{{ toolLabel(item.name) }}</span>
      <span v-if="item.result_missing" data-test="result-missing" class="text-xs text-fg-muted">Resultado não disponível no histórico</span>
      <span v-else-if="running" class="animate-pulse text-xs text-primary-soft">rodando…</span>
      <span v-else-if="isError" class="text-xs text-diff-del-fg">erro</span>
      <span v-else-if="!item.result" class="text-xs text-fg-muted">sem resultado</span>
    </button>
    <div v-show="open" class="flex flex-col gap-2 border-t border-line px-3 py-2">
      <div>
        <div class="mb-1 text-xs text-fg-muted">Entrada</div>
        <TruncatedText :text="input" />
      </div>
      <div v-if="item.result">
        <div class="mb-1 text-xs text-fg-muted">Resultado</div>
        <div :class="isError ? 'text-diff-del-fg' : ''" :data-test="isError ? 'tool-error' : 'tool-output'">
          <TruncatedText :text="output" />
        </div>
      </div>
    </div>
  </div>
</template>
