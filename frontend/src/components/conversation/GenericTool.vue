<script setup lang="ts">
import { computed, ref } from 'vue'
import { prettyJson, resultText, toolLabel } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'
import WorkHeader from './WorkHeader.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()
const open = ref(false)

const input = computed(() => prettyJson(props.item.input))
const output = computed(() => resultText(props.item.result?.content))
const isError = computed(() => props.item.result?.is_error === true)
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const status = computed<'ok' | 'running' | 'error' | 'idle'>(() => {
  if (running.value) return 'running'
  if (isError.value) return 'error'
  return props.item.result ? 'ok' : 'idle'
})
const meta = computed(() => (!props.item.result && !props.item.result_missing && !running.value ? 'sem resultado' : undefined))
</script>

<template>
  <div class="overflow-hidden rounded-lg border bg-panel" :class="isError ? 'border-diff-del-fg/40' : 'border-line'">
    <WorkHeader
      kind="tool"
      as="button"
      :desc="toolLabel(item.name)"
      mono
      :status="status"
      :meta="meta"
      :open="open"
      :aria-expanded="open"
      @click="open = !open"
    >
      <template v-if="item.result_missing" #trail>
        <span data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      </template>
    </WorkHeader>
    <div v-show="open" class="flex flex-col gap-2 border-t border-line px-3 py-2">
      <div>
        <div class="mb-1 text-xs text-fg-subtle">Entrada</div>
        <TruncatedText :text="input" />
      </div>
      <div v-if="item.result">
        <div class="mb-1 text-xs text-fg-subtle">Resultado</div>
        <div :class="isError ? 'text-diff-del-fg' : ''" :data-test="isError ? 'tool-error' : 'tool-output'">
          <TruncatedText :text="output" />
        </div>
      </div>
    </div>
  </div>
</template>
