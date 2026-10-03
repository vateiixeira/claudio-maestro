<script setup lang="ts">
import { computed, ref } from 'vue'
import { countLines, resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'
import WorkHeader from './WorkHeader.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()
const open = ref(false)

const content = computed(() => resultText(props.item.result?.content))
const lineCount = computed(() => countLines(content.value))
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const status = computed<'ok' | 'running' | 'error' | 'idle'>(() => {
  if (running.value) return 'running'
  if (props.item.result?.is_error) return 'error'
  return props.item.result ? 'ok' : 'idle'
})
const meta = computed(() => {
  if (status.value === 'ok') return `${lineCount.value} ${lineCount.value === 1 ? 'linha' : 'linhas'}`
  return !props.item.result && !props.item.result_missing && !running.value ? 'sem resultado' : undefined
})
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line bg-panel">
    <WorkHeader
      kind="read"
      as="button"
      :desc="str(item.input.file_path)"
      mono
      :status="status"
      :meta="meta"
      :open="open"
      :aria-expanded="open"
      :disabled="!item.result"
      @click="open = !open"
    >
      <template v-if="item.result_missing" #trail>
        <span data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      </template>
    </WorkHeader>
    <div v-if="open && item.result" class="border-t border-line px-3 py-2" :class="{ 'text-diff-del-fg': item.result.is_error }">
      <TruncatedText :text="content" />
    </div>
  </div>
</template>
