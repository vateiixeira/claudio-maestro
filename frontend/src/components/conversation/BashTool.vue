<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { BACKGROUND_LABEL, backgroundState } from '../../conversation/background'
import { SUBAGENT_FOCUS_KEY } from '../../conversation/subagents'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import BashPane from './BashPane.vue'
import WorkHeader from './WorkHeader.vue'

// `headless`: inside a work block the row above is the header, so the card is just its body.
const props = defineProps<{ item: ToolItem; sessionActive?: boolean; headless?: boolean }>()

const output = computed(() => resultText(props.item.result?.content))
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const isError = computed(() => props.item.result?.is_error === true)
// Started in the background: the card follows the task, not the launch result.
const background = computed(() => backgroundState(props.item))
const summary = computed(() => props.item.background?.summary ?? '')
const command = computed(() => str(props.item.input.command))
// Without a description the header shows the first line of the command, so the row is never empty.
const description = computed(() => str(props.item.input.description))
const commandLine = computed(() => command.value.split('\n', 1)[0] ?? '')
// The strip and the turn footer can ask to reach a background command: the card is marked for a moment.
const focus = inject(SUBAGENT_FOCUS_KEY, ref(null))
const highlighted = computed(() => background.value !== null && focus.value?.id === props.item.id)
// What the header says: running, failed, done, or nothing to report yet. A background command follows its task.
const status = computed<'ok' | 'running' | 'error' | 'stopped' | 'idle'>(() => {
  if (running.value || background.value === 'running') return 'running'
  if (background.value === 'failed') return 'error'
  if (background.value === 'completed') return 'ok'
  if (background.value !== null) return 'idle'
  if (isError.value) return 'error'
  if (props.item.result_missing || !props.item.result) return 'idle'
  return 'ok'
})
const meta = computed(() => (!props.item.result && !props.item.result_missing && !running.value ? 'sem resultado' : undefined))
</script>

<template>
  <div
    class="min-w-0 scroll-mt-14 rounded-lg outline-none"
    :class="highlighted ? 'ring-2 ring-primary' : ''"
    :data-subagent-id="background !== null ? item.id : undefined"
    :data-highlighted="highlighted ? 'true' : undefined"
    :tabindex="background !== null ? -1 : undefined"
  >
    <div data-test="bash-box" :class="headless ? '[&>:first-child]:border-t-0' : 'overflow-hidden rounded-lg border border-line bg-panel'">
      <WorkHeader
        v-if="!headless"
        data-test="bash-header"
        kind="bash"
        :desc="description || commandLine"
        :mono="!description"
        :status="status"
        :meta="item.result_missing ? undefined : meta"
      >
        <template v-if="item.result_missing" #trail>
          <span data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
        </template>
        <template v-if="background && !running && !item.result_missing" #status>
          <span
            data-test="bash-background"
            :data-status="background"
            class="flex shrink-0 items-center gap-1.5 font-mono text-[0.6875rem]"
            :class="background === 'running' ? 'text-secondary-soft' : background === 'completed' ? 'text-primary-soft' : background === 'failed' ? 'text-diff-del-fg' : 'text-fg-subtle'"
          >
            <span v-if="background === 'running'" data-test="bash-background-dot" class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-secondary motion-reduce:animate-none" aria-hidden="true" />
            {{ BACKGROUND_LABEL[background] }}
          </span>
        </template>
      </WorkHeader>
      <BashPane data-test="bash-command" label="IN" name="Comando" copy-label="Copiar comando" :text="command" :preview="2" class="border-t border-line" />
      <div v-if="!running && output" data-test="bash-output" class="border-t border-line">
        <div :data-test="isError ? 'tool-error' : 'tool-output'">
          <BashPane label="OUT" name="Saída" copy-label="Copiar saída" :text="output" :preview="isError ? 12 : 4" :error="isError" />
        </div>
      </div>
    </div>
    <p v-if="summary" data-test="bash-background-summary" class="m-0 mt-1 text-xs text-fg-subtle">{{ summary }}</p>
  </div>
</template>
