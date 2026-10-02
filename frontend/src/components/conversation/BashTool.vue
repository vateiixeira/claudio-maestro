<script setup lang="ts">
import { computed } from 'vue'
import { BACKGROUND_LABEL, backgroundState } from '../../conversation/background'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import BashPane from './BashPane.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()

const output = computed(() => resultText(props.item.result?.content))
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const isError = computed(() => props.item.result?.is_error === true)
// Started in the background: the card follows the task, not the launch result.
const background = computed(() => backgroundState(props.item))
const backgroundFailed = computed(() => background.value === 'failed')
const summary = computed(() => props.item.background?.summary ?? '')
const command = computed(() => str(props.item.input.command))
// The dot says it all: running pulses, failed is red, done is green; no result yet stays grey.
const dot = computed(() => {
  if (running.value) return 'running'
  if (isError.value || backgroundFailed.value) return 'error'
  if (props.item.result_missing || !props.item.result) return 'idle'
  return 'ok'
})
</script>

<template>
  <div class="min-w-0">
    <div data-test="bash-header" class="flex min-w-0 items-center gap-2 text-sm leading-5">
      <span
        data-test="bash-status-dot"
        :data-state="dot"
        class="h-2 w-2 shrink-0 rounded-full"
        :class="[
          dot === 'running' ? 'animate-pulse bg-primary motion-reduce:animate-none' : dot === 'error' ? 'bg-diff-del-fg' : dot === 'ok' ? 'bg-primary' : 'bg-fg-subtle',
        ]"
        aria-hidden="true"
      />
      <span class="shrink-0 font-semibold text-fg">Comando</span>
      <span v-if="str(item.input.description)" class="min-w-0 truncate text-xs text-fg-subtle">{{ str(item.input.description) }}</span>
      <span class="grow" />
      <span v-if="running" class="sr-only">rodando…</span>
      <span v-else-if="item.result_missing" data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      <span
        v-else-if="background"
        data-test="bash-background"
        :data-status="background"
        class="flex shrink-0 items-center gap-1.5 text-xs"
        :class="background === 'running' ? 'text-primary-soft' : background === 'completed' ? 'text-primary-soft' : background === 'failed' ? 'text-diff-del-fg' : 'text-fg-subtle'"
      >
        <span v-if="background === 'running'" data-test="bash-background-dot" class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-primary motion-reduce:animate-none" aria-hidden="true" />
        {{ BACKGROUND_LABEL[background] }}
      </span>
      <span v-else-if="isError" class="sr-only">falhou</span>
      <span v-else-if="!item.result" class="shrink-0 text-xs text-fg-subtle">sem resultado</span>
    </div>
    <div data-test="bash-box" class="mt-1 overflow-hidden rounded-md border border-line bg-panel">
      <BashPane data-test="bash-command" label="IN" name="Comando" copy-label="Copiar comando" :text="command" :preview="2" />
      <div v-if="!running && output" data-test="bash-output" class="border-t border-line">
        <div :data-test="isError ? 'tool-error' : 'tool-output'">
          <BashPane label="OUT" name="Saída" copy-label="Copiar saída" :text="output" :preview="isError ? 12 : 4" :error="isError" />
        </div>
      </div>
    </div>
    <p v-if="summary" data-test="bash-background-summary" class="m-0 mt-1 text-xs text-fg-subtle">{{ summary }}</p>
  </div>
</template>
